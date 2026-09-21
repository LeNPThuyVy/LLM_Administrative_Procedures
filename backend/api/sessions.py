import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from context.database import AsyncSessionLocal
from context.models import User, ChatSession, Message


router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"]
)


class CreateSessionRequest(BaseModel):
    user_id: uuid.UUID


@router.post("")
async def create_session(request: CreateSessionRequest):
    async with AsyncSessionLocal() as db:

        # Kiểm tra user có tồn tại không
        user_result = await db.execute(
            select(User).where(
                User.id == request.user_id
            )
        )

        user = user_result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # Tạo session đúng cho user đang đăng nhập
        session = ChatSession(
            id=uuid.uuid4(),
            user_id=user.id
        )

        db.add(session)
        await db.commit()
        await db.refresh(session)

        return {
            "session_id": str(session.id),
            "user_id": str(session.user_id),
            "created_at": (
                session.created_at.isoformat()
                if session.created_at
                else None
            )
        }


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: uuid.UUID,
    user_id: uuid.UUID
):
    async with AsyncSessionLocal() as db:

        session_result = await db.execute(
            select(ChatSession)
            .where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id
            )
        )

        session = session_result.scalar_one_or_none()

        if session is None:
            raise HTTPException(
                status_code=404,
                detail="Session not found or does not belong to user"
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