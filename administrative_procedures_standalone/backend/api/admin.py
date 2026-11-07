from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

import backend.admin_auth as admin_auth
from backend.rate_limit import ChatRateLimiter
from backend.security import require_ingestion_admin
from backend.session_access import COOKIE_SECURE


router = APIRouter(prefix="/api/admin", tags=["admin"])

LOGIN_ATTEMPTS_PER_WINDOW = 10
LOGIN_WINDOW_SECONDS = 15 * 60

login_rate_limiter = ChatRateLimiter(
    limit=LOGIN_ATTEMPTS_PER_WINDOW,
    window_seconds=LOGIN_WINDOW_SECONDS,
)


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(
        min_length=1,
        max_length=admin_auth.MAX_PASSWORD_LENGTH,
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login")
async def admin_login(
    credentials: AdminLoginRequest,
    request: Request,
    response: Response,
):
    client_ip = _client_ip(request)

    if not login_rate_limiter.allow(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Bạn thử đăng nhập quá nhiều lần. Vui lòng thử lại sau.",
            headers={"Retry-After": str(LOGIN_WINDOW_SECONDS)},
        )

    username = credentials.username.strip()

    try:
        result = await admin_auth.login(username, credentials.password)
    except (SQLAlchemyError, OSError) as exc:
        print(f"[ADMIN] không kiểm tra được đăng nhập: {exc!r}")
        raise HTTPException(
            status_code=503,
            detail="Hệ thống đăng nhập tạm thời không khả dụng.",
        )

    if result is None:
        await admin_auth.record_audit("LOGIN_FAILED", username, client_ip, 401)
        raise HTTPException(
            status_code=401,
            detail="Tên đăng nhập hoặc mật khẩu không đúng.",
        )

    admin, token, expires_at = result

    response.set_cookie(
        key=admin_auth.ADMIN_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        max_age=admin_auth.admin_session_hours() * 3600,
    )
    await admin_auth.record_audit("LOGIN", admin.username, client_ip, 200)

    return {
        "username": admin.username,
        "expires_at": expires_at.isoformat(),
    }


@router.post("/logout")
async def admin_logout(request: Request, response: Response):
    await admin_auth.logout(request.cookies.get(admin_auth.ADMIN_COOKIE_NAME))
    response.delete_cookie(
        key=admin_auth.ADMIN_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="strict",
    )
    return {"status": "ok"}


@router.get("/me")
async def admin_me(
    admin: admin_auth.AdminIdentity = Depends(require_ingestion_admin),
):
    return {"username": admin.username}
