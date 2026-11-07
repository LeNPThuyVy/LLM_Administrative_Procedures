from fastapi import HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

import backend.admin_auth as admin_auth


async def resolve_admin(token: str | None) -> admin_auth.AdminIdentity:
    """Trả về quản trị viên của phiên, hoặc từ chối request."""
    try:
        admin = await admin_auth.authenticate(token)
    except (SQLAlchemyError, OSError) as exc:
        print(f"[ADMIN] không kiểm tra được phiên đăng nhập: {exc!r}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hệ thống đăng nhập tạm thời không khả dụng.",
        ) from exc

    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cần đăng nhập quản trị để thực hiện thao tác này.",
        )

    return admin


async def require_ingestion_admin(
    request: Request,
) -> admin_auth.AdminIdentity:
    """
    Bảo vệ các API có khả năng thay đổi domain/dataset.

    Middleware đã xác thực thì dùng lại kết quả, tránh truy vấn DB hai lần.
    """
    admin = getattr(request.state, "admin", None)
    if admin is not None:
        return admin

    return await resolve_admin(
        request.cookies.get(admin_auth.ADMIN_COOKIE_NAME)
    )
