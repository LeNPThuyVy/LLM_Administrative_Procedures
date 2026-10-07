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

from context.structured_context import (
    extract_structured_context,
    merge_long_term_memory,
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

        summary = summary_result.scalar_one_or_none()

        structured_result = await db.execute(
            select(StructuredContext)
            .where(
                StructuredContext.session_id
                == session_id
            )
        )

        structured = structured_result.scalar_one_or_none()

        memory_result = await db.execute(
            select(LongTermMemory)
            .where(
                LongTermMemory.user_id
                == session.user_id
            )
        )

        memory = memory_result.scalar_one_or_none()

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

        # =========================
        # GET SESSION
        # =========================
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

        # =========================
        # SAVE USER MESSAGE
        # =========================
        user_message = Message(
            session_id=session_id,
            role="user",
            content=query
        )

        db.add(user_message)

        # =========================
        # SAVE ASSISTANT MESSAGE
        # =========================
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

        db.add(assistant_message)

        # =========================
        # LOAD OLD STRUCTURED CONTEXT
        # =========================
        structured_result = await db.execute(
            select(StructuredContext)
            .where(
                StructuredContext.session_id
                == session_id
            )
        )

        existing_structured = (
            structured_result.scalar_one_or_none()
        )

        old_structured_context = (
            existing_structured.data
            if existing_structured
            else {}
        )

        # =========================
        # AUTO EXTRACT STRUCTURED CONTEXT
        # =========================
        new_structured_context = (
            extract_structured_context(
                message=query,
                old_context=old_structured_context
            )
        )

        # =========================
        # SAVE STRUCTURED CONTEXT
        # =========================
        if existing_structured is None:

            new_structured_record = StructuredContext(
                session_id=session_id,
                data=new_structured_context
            )

            db.add(new_structured_record)

        else:

            existing_structured.data = (
                new_structured_context
            )

        # =========================
        # LOAD LONG TERM MEMORY (theo user_id, không phải
        # session_id — phải sống xuyên suốt nhiều session)
        # =========================
        memory_result = await db.execute(
            select(LongTermMemory)
            .where(
                LongTermMemory.user_id
                == session.user_id
            )
        )

        existing_memory = (
            memory_result.scalar_one_or_none()
        )

        old_memory_data = (
            existing_memory.data
            if existing_memory
            else {}
        )

        # =========================
        # MERGE (không ghi đè) LONG TERM MEMORY
        # =========================
        new_memory_data = merge_long_term_memory(
            old_memory=old_memory_data,
            new_structured_context=new_structured_context,
        )

        # =========================
        # SAVE LONG TERM MEMORY
        # =========================
        if existing_memory is None:

            new_memory_record = LongTermMemory(
                user_id=session.user_id,
                data=new_memory_data,
            )

            db.add(new_memory_record)

        else:

            existing_memory.data = new_memory_data

        # =========================
        # COMMIT
        # =========================
        await db.commit()

    # =========================
    # UPDATE CONVERSATION SUMMARY
    # =========================
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

        # Sử dụng LLM để tóm tắt
        from context.llm_summarizer import summarize_text_with_llm
        
        # Nếu summary cũ đã tồn tại, nối thêm nó vào để LLM có ngữ cảnh dài hạn
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
        
        if summary and summary.summary:
            summary_text = f"Tóm tắt trước đó: {summary.summary}\nLịch sử mới:\n{summary_text}"

        print(f"[MEMORY] Bắt đầu gọi LLM tóm tắt cho session {session_id}...")
        summarized_text = await summarize_text_with_llm(summary_text)
        print(f"[MEMORY] Đã tóm tắt xong cho session {session_id}.")

        if summary is None:

            summary = ConversationSummary(
                session_id=session_id,
                summary=summarized_text
            )

            db.add(summary)

        else:

            summary.summary = summarized_text

        await db.commit()