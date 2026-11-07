from fastapi import HTTPException, status
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

import backend.upload_security as upload_security
from backend.security import require_ingestion_admin


DOMAIN_WRITE_PREFIX = "/api/domains/"
DOMAIN_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Phần header và boundary của multipart, nằm ngoài dung lượng tệp.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024


def _body_limit_bytes() -> int:
    return upload_security.MAX_UPLOAD_SIZE_BYTES + MULTIPART_OVERHEAD_BYTES


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=(
            f"Dữ liệu vượt quá giới hạn "
            f"{upload_security.MAX_UPLOAD_SIZE_MB} MB."
        ),
    )


def _check_declared_length(raw_length: str | None) -> None:
    if raw_length is None:
        return

    if not raw_length.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content-Length không hợp lệ.",
        )

    if int(raw_length) > _body_limit_bytes():
        raise _too_large()


class DomainWriteGuardMiddleware:
    """
    Kiểm tra quyền và kích thước trước khi đọc body của API ghi domain.

    FastAPI parse form trước khi chạy dependency, nên riêng
    require_ingestion_admin không ngăn được upload từ người chưa xác thực.
    Dependency vẫn được giữ lại như một lớp bảo vệ thứ hai.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] not in DOMAIN_WRITE_METHODS
            or not scope["path"].startswith(DOMAIN_WRITE_PREFIX)
        ):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)

        try:
            require_ingestion_admin(headers.get("x-admin-key"))
            _check_declared_length(headers.get("content-length"))
        except HTTPException as exc:
            response = JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
            )
            await response(scope, receive, send)
            return

        received_bytes = 0

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()

            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))

                if received_bytes > _body_limit_bytes():
                    raise _too_large()

            return message

        await self.app(scope, limited_receive, send)
