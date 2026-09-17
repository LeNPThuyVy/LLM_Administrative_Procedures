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

async def update_memory(
    session_id,
    query: str,
    final_result: dict
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

        user_message = Message(
            session_id=session_id,
            role="user",
            content=query
        )

        answer = final_result.get(
            "answer",
            ""
        )

        evidence_list = final_result.get(
            "evidence_list",
            []
        )

        assistant_message = Message(
            session_id=session_id,
            role="assistant",
            content=answer,
            evidence=evidence_list
        )

        db.add(user_message)
        db.add(assistant_message)

        new_structured_context = final_result.get(
            "structured_context",
            {}
        )

        if new_structured_context:
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

            if structured is None:
                structured = StructuredContext(
                    session_id=session_id,
                    data=new_structured_context
                )

                db.add(structured)

            else:
                current_data = dict(
                    structured.data or {}
                )

                current_data.update(
                    new_structured_context
                )

                structured.data = current_data

        await db.commit()

        await _update_conversation_summary(
            session_id=session_id
        )

SUMMARY_TRIGGER = 20
RECENT_KEEP = 10


async def _update_conversation_summary(
    session_id
):
    async with AsyncSessionLocal() as db:

        result = await db.execute(
            select(Message)
            .where(
                Message.session_id == session_id
            )
            .order_by(
                Message.created_at.asc()
            )
        )

        messages = list(
            result.scalars().all()
        )

        if len(messages) < SUMMARY_TRIGGER:
            return

        old_messages = messages[:-RECENT_KEEP]

        if not old_messages:
            return

        summary_text = " | ".join(
            f"{message.role}: {message.content}"
            for message in old_messages
        )

        if len(summary_text) > 3000:
            summary_text = summary_text[-3000:]

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

        if summary is None:
            summary = ConversationSummary(
                session_id=session_id,
                summary=summary_text
            )

            db.add(summary)

        else:
            summary.summary = summary_text

        await db.commit()