"""
Test riêng cho fix long_term_memory (2026-09-27).

Chứng minh đúng điều mà bug cũ KHÔNG làm được:
- Cùng 1 user, mở 1 session MỚI (giả lập quay lại sau vài ngày)
- structured_context của session mới phải TRẮNG (đúng, vì nó theo session)
- long_term_memory phải CÒN NHỚ (vì nó theo user, không theo session)

Trước khi sửa: long_term_memory bị khoá theo session_id và bị ghi đè
bằng structured_context mỗi lượt -> session mới sẽ luôn thấy
long_term_memory rỗng, y hệt structured_context. Test này sẽ FAIL
trên code cũ và PASS trên code đã sửa.
"""
import asyncio

from context.database import AsyncSessionLocal
from context.models import User, ChatSession
from context.context_service import get_context, update_memory


async def create_user():
    async with AsyncSessionLocal() as db:
        user = User(name="Test Cross-Session")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


async def create_session(user_id):
    async with AsyncSessionLocal() as db:
        session = ChatSession(user_id=user_id)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session.id


async def run_test():
    user_id = await create_user()

    print("=" * 70)
    print("USER ID:", user_id)
    print("=" * 70)

    # ---- SESSION 1 (lần đầu, vài ngày trước) ----
    session_1 = await create_session(user_id)

    await update_memory(
        session_id=session_1,
        query="Tôi muốn làm thủ tục đăng ký thường trú ở TP.HCM",
        final_result={
            "answer": "Đây là câu trả lời session 1",
            "evidence_list": [],
        },
    )

    print("\nSESSION 1 - vừa hỏi xong, đóng tab / hết phiên.")

    # ---- SESSION 2 (user quay lại, session_id HOÀN TOÀN MỚI) ----
    session_2 = await create_session(user_id)

    context_session_2 = await get_context(
        session_id=session_2,
        query="Tôi cần chuẩn bị giấy tờ gì?",
    )

    structured = context_session_2["structured_context"]
    memory = context_session_2["long_term_memory"]

    print("\nSESSION 2 (session_id mới, cùng user) - trước khi hỏi gì:")
    print("structured_context:", structured)
    print("long_term_memory:", memory)

    errors = []

    # structured_context phải TRẮNG vì đây là session mới, chưa hỏi gì
    if structured.get("procedure_name") is not None:
        errors.append(
            "structured_context của session mới KHÔNG được có "
            "procedure_name (nó phải theo session, không phải user)"
        )

    # long_term_memory phải CÒN NHỚ vì nó theo user
    if memory.get("procedure_name") != "Đăng ký thường trú":
        errors.append(
            "long_term_memory phải nhớ procedure_name từ session 1 "
            f"nhưng nhận được: {memory.get('procedure_name')!r}"
        )

    if memory.get("location") != "TP.HCM":
        errors.append(
            "long_term_memory phải nhớ location từ session 1 "
            f"nhưng nhận được: {memory.get('location')!r}"
        )

    if "Đăng ký thường trú" not in memory.get("procedure_history", []):
        errors.append(
            "long_term_memory.procedure_history phải chứa thủ tục "
            "đã hỏi ở session 1"
        )

    print()
    if errors:
        print("CROSS-SESSION LONG TERM MEMORY TEST FAILED")
        for e in errors:
            print("-", e)
        raise SystemExit(1)

    print("CROSS-SESSION LONG TERM MEMORY TEST PASSED")
    print(
        "structured_context tách biệt theo session, "
        "long_term_memory sống xuyên suốt theo user."
    )
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_test())
