import asyncio
import uuid

from context.database import AsyncSessionLocal
from context.models import (
    User,
    ChatSession,
    Message,
    StructuredContext,
    ConversationSummary,
    LongTermMemory,
)


async def seed_data():
    async with AsyncSessionLocal() as db:

        user_id = uuid.uuid4()
        session_id = uuid.uuid4()

        # 1. Tạo user trước
        user = User(
            id=user_id,
            name="Pham Nhat Minh",
            email=f"minh_{user_id}@example.com"
        )

        db.add(user)
        await db.commit()

        print("User created:", user_id)

        # 2. Sau khi user tồn tại mới tạo session
        session = ChatSession(
            id=session_id,
            user_id=user_id
        )

        db.add(session)
        await db.commit()

        print("Session created:", session_id)

        # 3. Messages
        message_1 = Message(
            session_id=session_id,
            role="user",
            content="Tôi muốn làm thủ tục đăng ký thường trú."
        )

        message_2 = Message(
            session_id=session_id,
            role="assistant",
            content="Bạn muốn đăng ký thường trú ở khu vực nào?"
        )

        # 4. Structured Context
        structured_context = StructuredContext(
            session_id=session_id,
            data={
                "procedure_name": "Đăng ký thường trú",
                "location": "TP.HCM"
            }
        )

        # 5. Conversation Summary
        conversation_summary = ConversationSummary(
            session_id=session_id,
            summary=(
                "Người dùng đang hỏi về thủ tục "
                "đăng ký thường trú tại TP.HCM."
            )
        )

        # 6. Long-term Memory
        long_term_memory = LongTermMemory(
            user_id=user_id,
            data={
                "preferred_language": "vi"
            }
        )

        db.add_all([
            message_1,
            message_2,
            structured_context,
            conversation_summary,
            long_term_memory,
        ])

        await db.commit()

        print("\n================================")
        print("Seed data created successfully.")
        print("USER_ID =", user_id)
        print("SESSION_ID =", session_id)
        print("================================")


if __name__ == "__main__":
    asyncio.run(seed_data())