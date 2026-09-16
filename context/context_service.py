from sqlalchemy import select

from context.database import AsyncSessionLocal
from context.models import (
    User,
    ChatSession,
    Message,
    StructuredContext,
    ConversationSummary,
    LongTermMemory
)


async def get_context(
    session_id,
    query: str
):
    async with AsyncSessionLocal() as db:

        session_result = await db.execute(
            select(ChatSession)
            .where(
                ChatSession.id == session_id
            )
        )

        session = session_result.scalar_one_or_none()

        if session is None:
            raise ValueError(
                f"Session not found: {session_id}"
            )

        user_result = await db.execute(
            select(User)
            .where(
                User.id == session.user_id
            )
        )

        user = user_result.scalar_one_or_none()

        messages_result = await db.execute(
            select(Message)
            .where(
                Message.session_id == session_id
            )
            .order_by(
                Message.created_at.desc()
            )
            .limit(10)
        )

        messages = list(
            reversed(
                messages_result.scalars().all()
            )
        )

        summary_result = await db.execute(
            select(ConversationSummary)
            .where(
                ConversationSummary.session_id
                == session_id
            )
        )

        summary = (
            summary_result.scalar_one_or_none()
        )

        structured_result = await db.execute(
            select(StructuredContext)
            .where(
                StructuredContext.session_id
                == session_id
            )
        )

        structured = (
            structured_result.scalar_one_or_none()
        )

        memory_result = await db.execute(
            select(LongTermMemory)
            .where(
                LongTermMemory.user_id
                == session.user_id
            )
        )

        memory = (
            memory_result.scalar_one_or_none()
        )

        return {
            "session": {
                "id": str(session.id)
            },

            "user": {
                "id": str(user.id),
                "name": user.name,
                "email": user.email
            } if user else {},

            "conversation_summary": (
                summary.summary
                if summary
                else ""
            ),

            "recent_messages": [
                {
                    "role": message.role,
                    "content": message.content
                }
                for message in messages
            ],

            "structured_context": (
                structured.data
                if structured
                else {}
            ),

            "long_term_memory": (
                memory.data
                if memory
                else {}
            )
        }