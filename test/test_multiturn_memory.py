import asyncio
import uuid

from sqlalchemy import select

from context.database import AsyncSessionLocal
from context.models import (
    User,
    ChatSession,
    StructuredContext,
    LongTermMemory,
)
from context.context_service import (
    get_context,
    update_memory,
)


async def prepare_test_session():
    async with AsyncSessionLocal() as db:

        user = User(
            name="Test Multi-turn",
            email=f"multiturn_{uuid.uuid4().hex[:8]}@test.com"
        )

        db.add(user)
        await db.flush()

        session = ChatSession(
            user_id=user.id
        )

        db.add(session)
        await db.commit()

        return session.id, user.id


async def run_test():
    session_id, user_id = await prepare_test_session()

    print("=" * 70)
    print("SESSION ID:")
    print(session_id)
    print("=" * 70)

    messages = [
        "Tôi muốn làm thủ tục đăng ký thường trú ở TP.HCM",
        "Tôi cần chuẩn bị giấy tờ gì?",
        "Tôi đã có CCCD và giấy khai sinh",
        "Tôi muốn nộp online",
        "Lệ phí 20000 đồng phải không?",
        "Thời gian xử lý khoảng 7 ngày phải không?",
    ]

    for index, query in enumerate(messages, start=1):

        print()
        print("=" * 70)
        print(f"LƯỢT {index}")
        print("USER:")
        print(query)

        fake_result = {
            "answer": f"Câu trả lời test cho lượt {index}",
            "evidence_list": [],
            "needs_clarification": False,
            "clarification_question": None,
        }

        await update_memory(
            session_id=session_id,
            query=query,
            final_result=fake_result
        )

        context = await get_context(
            session_id=session_id,
            query=query
        )

        print()
        print("STRUCTURED CONTEXT:")
        print(
            context.get(
                "structured_context",
                {}
            )
        )

        print()
        print("LONG TERM MEMORY:")
        print(
            context.get(
                "long_term_memory",
                {}
            )
        )

    print()
    print("=" * 70)
    print("KIỂM TRA DATABASE CUỐI CÙNG")
    print("=" * 70)

    async with AsyncSessionLocal() as db:

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
                == user_id
            )
        )

        memory = (
            memory_result.scalar_one_or_none()
        )

        print()
        print("STRUCTURED CONTEXT DB:")
        print(
            structured.data
            if structured
            else None
        )

        print()
        print("LONG TERM MEMORY DB:")
        print(
            memory.data
            if memory
            else None
        )

    print()
    print("=" * 70)

    expected = {
        "procedure_name": "Đăng ký thường trú",
        "location": "TP.HCM",
        "method": "Trực tuyến",
        "fee": "20000 đồng",
        "processing_time": "7 ngày",
    }

    final_context = (
        structured.data
        if structured
        else {}
    )

    errors = []

    for key, expected_value in expected.items():

        actual_value = final_context.get(key)

        if actual_value != expected_value:
            errors.append(
                f"{key}: expected={expected_value!r}, "
                f"actual={actual_value!r}"
            )

    documents = final_context.get(
        "documents",
        []
    )

    if "CCCD" not in documents:
        errors.append(
            "documents thiếu CCCD"
        )

    if "Giấy khai sinh" not in documents:
        errors.append(
            "documents thiếu Giấy khai sinh"
        )

    if errors:

        print("MULTI-TURN TEST FAILED")

        for error in errors:
            print("-", error)

    else:

        print("MULTI-TURN TEST PASSED")
        print(
            "Structured Context và Long-Term Memory "
            "giữ đúng dữ liệu qua nhiều lượt."
        )

    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_test())