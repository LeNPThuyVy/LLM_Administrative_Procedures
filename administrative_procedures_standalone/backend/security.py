import os
import secrets
from typing import Optional

from fastapi import Header, HTTPException, status


def require_ingestion_admin(
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
) -> None:
    """
    Bảo vệ các API có khả năng thay đổi domain/dataset.

    INGESTION_ADMIN_KEY phải được cấu hình ở môi trường server.
    Client quản trị gửi key qua header X-Admin-Key.
    """
    expected_key = os.getenv("INGESTION_ADMIN_KEY", "").strip()

    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API quản trị dữ liệu chưa được cấu hình khóa bảo mật.",
        )

    if not x_admin_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu khóa xác thực quản trị.",
        )

    if not secrets.compare_digest(x_admin_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Khóa xác thực quản trị không hợp lệ.",
        )
