import os
import uuid

from sqlalchemy import select

from context.context_service import ANONYMOUS_USER_ID, _ensure_uuid
from context.database import AsyncSessionLocal
from context.models import ChatSession


COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() == "true"


class SessionAccessDenied(Exception):
    """Người gọi không phải chủ sở hữu của session được yêu cầu."""


def parse_user_cookie(raw_user_id: str | None) -> uuid.UUID | None:
    """
    Đọc user_id từ cookie.

    ANONYMOUS_USER_ID là hằng số ai cũng tính được, nên không bao giờ được
    coi là danh tính của người gọi.
    """
    try:
        user_id = uuid.UUID(raw_user_id) if raw_user_id else None
    except ValueError:
        return None

    return None if user_id == ANONYMOUS_USER_ID else user_id


async def assert_session_access(
    session_id: str,
    user_cookie: str | None,
) -> None:
    """
    Chặn việc đọc hoặc ghi vào session của người khác qua chat.

    Session chưa tồn tại được cho qua vì chưa có dữ liệu để bảo vệ
    (benchmark và client API tạo session bằng UUID mới, không có cookie).
    Session thuộc user anonymous.local cũng không có chủ riêng.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChatSession.user_id).where(
                ChatSession.id == _ensure_uuid(session_id)
            )
        )
        owner_id = result.scalar_one_or_none()

    if owner_id is None or owner_id == ANONYMOUS_USER_ID:
        return

    if parse_user_cookie(user_cookie) != owner_id:
        raise SessionAccessDenied(str(session_id))
