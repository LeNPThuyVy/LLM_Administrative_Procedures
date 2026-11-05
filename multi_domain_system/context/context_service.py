import asyncio
import uuid
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


def _ensure_uuid(val) -> uuid.UUID:
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(val))


async def _ensure_session(db, session_id: uuid.UUID) -> ChatSession:
    session_result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if session is None:
        anonymous_user_id = uuid.uuid5(uuid.NAMESPACE_DNS, "anonymous.local")
        user_res = await db.execute(select(User).where(User.id == anonymous_user_id))
        if not user_res.scalar_one_or_none():
            db.add(User(id=anonymous_user_id, name="Anonymous", email=None))
            await db.flush()
        session = ChatSession(id=session_id, user_id=anonymous_user_id)
        db.add(session)
        await db.commit()
    return session


async def _fetch_user(user_id):
    if not user_id:
        return None
    async with AsyncSessionLocal() as s:
        res = await s.execute(select(User).where(User.id == user_id))
        return res.scalar_one_or_none()

async def _fetch_messages(session_id):
    import my_config as cfg
    limit_count = getattr(cfg, "HISTORY_STORE_TURNS", 10) * 2
    async with AsyncSessionLocal() as s:
        res = await s.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit_count)
        )
        return list(reversed(res.scalars().all()))

async def _fetch_summary(session_id):
    async with AsyncSessionLocal() as s:
        res = await s.execute(
            select(ConversationSummary).where(ConversationSummary.session_id == session_id)
        )
        return res.scalar_one_or_none()

async def _fetch_structured(session_id):
    async with AsyncSessionLocal() as s:
        res = await s.execute(
            select(StructuredContext).where(StructuredContext.session_id == session_id)
        )
        return res.scalar_one_or_none()

async def _fetch_memory(user_id):
    if not user_id:
        return None
    async with AsyncSessionLocal() as s:
        res = await s.execute(
            select(LongTermMemory).where(LongTermMemory.user_id == user_id)
        )
        return res.scalar_one_or_none()


def derive_active_entity(messages: list, current_domain: str | None = None) -> dict | None:
    """
    Suy ra thực thể (thủ tục) đang hoạt động từ tin nhắn assistant gần nhất.
    Duyệt ngược từ các tin nhắn gần nhất (tối đa 4 tin nhắn / 2 lượt gần nhất).
    Trích top-1 evidence (document_id, title) từ citations hoặc claims.

    Phase 4: Nếu tin nhắn assistant thuộc domain khác với current_domain,
    bỏ qua active_entity cũ (trả về None) để tránh soft-boost chéo domain.
    """
    if not messages:
        return None

    # Xét tối đa 4 tin nhắn gần nhất (2 lượt)
    recent = messages[-4:] if len(messages) > 4 else messages

    for msg in reversed(recent):
        role = getattr(msg, "role", None) if hasattr(msg, "role") else (msg.get("role") if isinstance(msg, dict) else None)
        if role != "assistant":
            continue

        evidence = getattr(msg, "evidence", None) if hasattr(msg, "evidence") else (msg.get("evidence") if isinstance(msg, dict) else None)
        if not evidence or not isinstance(evidence, list):
            continue

        for claim in evidence:
            if not isinstance(claim, dict):
                continue

            msg_domain = claim.get("domain")
            if current_domain and msg_domain and msg_domain != current_domain:
                # Đổi domain giữa session -> reset active entity
                return None

            citations = claim.get("citations", [])
            if isinstance(citations, list):
                for cit in citations:
                    if not isinstance(cit, dict):
                        continue
                    doc_id = cit.get("document_id") or cit.get("doc_id") or ""
                    title = cit.get("title") or ""
                    if title or doc_id:
                        return {
                            "doc_id": doc_id,
                            "title": title,
                        }
            # Fallback nếu claim có trực tiếp document_id/title
            doc_id = claim.get("document_id") or claim.get("doc_id") or ""
            title = claim.get("title") or ""
            if title or doc_id:
                return {
                    "doc_id": doc_id,
                    "title": title,
                }

    return None


async def get_context(
    session_id,
    query: str,
    domain: str | None = None,
):
    import my_config as cfg

    s_id = _ensure_uuid(session_id)
    async with AsyncSessionLocal() as db:
        session = await _ensure_session(db, s_id)

    # Truy vấn các bảng qua pool: chỉ fetch summary/memory/user khi cờ tương ứng bật
    fetch_user = getattr(cfg, "ENABLE_LONG_TERM_MEMORY", False)
    fetch_summary = getattr(cfg, "ENABLE_CONVERSATION_SUMMARY", False)
    fetch_memory = getattr(cfg, "ENABLE_LONG_TERM_MEMORY", False)
    fetch_structured = not getattr(cfg, "SLIM_CONTEXT", False)

    messages_task = _fetch_messages(s_id)
    structured_task = _fetch_structured(s_id) if fetch_structured else None
    user_task = _fetch_user(session.user_id) if fetch_user else None
    summary_task = _fetch_summary(s_id) if fetch_summary else None
    memory_task = _fetch_memory(session.user_id) if fetch_memory else None

    gathered = await asyncio.gather(
        messages_task,
        structured_task if structured_task else asyncio.sleep(0),
        user_task if user_task else asyncio.sleep(0),
        summary_task if summary_task else asyncio.sleep(0),
        memory_task if memory_task else asyncio.sleep(0),
    )
    messages = gathered[0]
    structured = gathered[1] if fetch_structured else None
    user = gathered[2] if user_task else None
    summary = gathered[3] if summary_task else None
    memory = gathered[4] if memory_task else None

    if getattr(cfg, "SLIM_CONTEXT", False):
        active_entity = derive_active_entity(messages, current_domain=domain)
        structured_data = {}
        if active_entity:
            if active_entity.get("title"):
                structured_data["procedure_name"] = active_entity["title"]
            if active_entity.get("doc_id"):
                structured_data["doc_id"] = active_entity["doc_id"]
    else:
        structured_data = structured.data if structured else {}

    return {
        "session": {
            "id": str(session.id)
        },
        "user": {
            "id": str(user.id),
            "name": user.name,
            "email": user.email
        } if user else {"id": str(session.user_id)},
        "conversation_summary": summary.summary if summary else "",
        "recent_messages": [
            {
                "role": message.role,
                "content": message.content
            }
            for message in messages
        ],
        "structured_context": structured_data,
        "long_term_memory": memory.data if memory else {}
    }


async def update_memory(
    session_id,
    query: str,
    final_result: dict
):
    import my_config as cfg
    s_id = _ensure_uuid(session_id)
    async with AsyncSessionLocal() as db:

        # =========================
        # GET OR CREATE SESSION
        # =========================
        session = await _ensure_session(db, s_id)

        # =========================
        # SAVE USER MESSAGE
        # =========================
        user_message = Message(
            session_id=s_id,
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
            session_id=s_id,
            role="assistant",
            content=answer,
            evidence=evidence_list
        )

        db.add(assistant_message)

        # =========================
        # STRUCTURED CONTEXT (chỉ khi SLIM_CONTEXT = False)
        # =========================
        if not getattr(cfg, "SLIM_CONTEXT", False):
            # LOAD OLD STRUCTURED CONTEXT
            structured_result = await db.execute(
                select(StructuredContext)
                .where(
                    StructuredContext.session_id
                    == s_id
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

            # AUTO EXTRACT STRUCTURED CONTEXT
            new_structured_context = (
                extract_structured_context(
                    message=query,
                    old_context=old_structured_context
                )
            )

            # SAVE STRUCTURED CONTEXT
            if existing_structured is None:
                new_structured_record = StructuredContext(
                    session_id=s_id,
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
        import my_config as cfg
        if getattr(cfg, "ENABLE_LONG_TERM_MEMORY", False):
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

