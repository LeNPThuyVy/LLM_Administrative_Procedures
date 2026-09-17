import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from context.database import AsyncSessionLocal
from context.models import User, ChatSession, Message


router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"]
)


@router.post("")
async def create_session():
    async with AsyncSessionLocal() as db:

        # Demo/PoC: lấy user đầu tiên trong DB
        user_result = await db.execute(
            select(User).limit(1)
        )

        user = user_result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=400,
                detail="No user found in database"
            )

        session = ChatSession(
            id=uuid.uuid4(),
            user_id=user.id
        )

        db.add(session)
        await db.commit()
        await db.refresh(session)

        return {
            "session_id": str(session.id),
            "created_at": (
                session.created_at.isoformat()
                if session.created_at
                else None
            )
        }


@router.get("/{session_id}/messages")
async def get_session_messages(session_id: uuid.UUID):
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