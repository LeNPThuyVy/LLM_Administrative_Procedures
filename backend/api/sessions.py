import uuid

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from context.database import AsyncSessionLocal
from context.models import ChatSession, Message


router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"]
)

COOKIE_NAME = "session_id"


# NOTE (2026-09-27): endpoint tạo session (POST /api/sessions) đã bị
# xoá khỏi đây. Trước đây nó nhận thẳng user_id từ client và tạo
# ChatSession cho user_id đó — giả định một mô hình "user đã đăng
# nhập, đã có user_id sẵn" hoàn toàn khác với mô hình thật của app:
# session ẩn danh, tự tạo qua cookie (xem
# backend/api/socket.py::bootstrap_session /
# ensure_anonymous_session). Hai đường tạo session song song này là
# nguồn gốc của bug — giờ chỉ còn DUY NHẤT MỘT nơi tạo session:
# GET /api/session/bootstrap.
#
# File này giờ chỉ còn nhiệm vụ đọc lại lịch sử tin nhắn của một
# session đã tồn tại.


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: uuid.UUID,
    request: Request,
):
    """
    Trả lịch sử tin nhắn của một session.

    Vì đây là session ẩn danh (không có tài khoản đăng nhập), quyền
    xem lịch sử được xác định bằng chính cookie session_id (HttpOnly,
    do server set ở bootstrap_session) — KHÔNG nhận user_id do client
    tự khai, vì client có thể tự sửa query param để xem lịch sử của
    session khác.
    """

    cookie_session_id = request.cookies.get(
        COOKIE_NAME
    )

    if not cookie_session_id:
        raise HTTPException(
            status_code=401,
            detail="Missing session_id cookie"
        )

    if cookie_session_id != str(session_id):
        raise HTTPException(
            status_code=403,
            detail=(
                "session_id cookie does not match "
                "the requested session"
            )
        )

    async with AsyncSessionLocal() as db:

        session_result = await db.execute(
            select(ChatSession)
            .where(
                ChatSession.id == session_id
            )
        )

        session = session_result.scalar_one_or_none()

        if session is None:
            raise HTTPException(
                status_code=404,
                detail="Session not found"
            )

        messages_result = await db.execute(
            select(Message)
            .where(
                Message.session_id == session_id
            )
            .order_by(
                Message.created_at.asc()
            )
        )

        messages = messages_result.scalars().all()

        return {
            "session_id": str(session.id),
            "user_id": str(session.user_id),
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                    "citations": (
                        message.evidence
                        if message.role == "assistant"
                        else None
                    ),
                    "created_at": (
                        message.created_at.isoformat()
                        if message.created_at
                        else None
                    )
                }
                for message in messages
            ]
        }