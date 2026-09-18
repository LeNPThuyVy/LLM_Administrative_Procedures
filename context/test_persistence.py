import asyncio
import uuid
import json

from context.database import AsyncSessionLocal
from context.models import User, ChatSession
from context.context_service import (
    update_memory,
    get_context
)


async def create_user_and_session(name: str):
    async with AsyncSessionLocal() as db:
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()

        user = User(
            id=user_id,
            name=name,
            email=f"{user_id}@example.com"
        )

        session = ChatSession(
            id=session_id,
            user_id=user_id
        )

        db.add(user)
        await db.commit()

        db.add(session)
        await db.commit()

        return session_id


async def main():
    session_1 = await create_user_and_session(
        "User Session 1"
    )

    session_2 = await create_user_and_session(
        "User Session 2"
    )

    await update_memory(
        session_id=session_1,
        query="Tôi muốn hỏi thủ tục thường trú",
        final_result={
            "answer": "Đây là câu trả lời session 1",
            "evidence_list": [
                {
                    "evidence_id": "s1_ev1"
                }
            ],
            "structured_context": {
                "procedure_name": "Đăng ký thường trú"
            }
        }
    )

    await update_memory(
        session_id=session_2,
        query="Tôi muốn hỏi về CCCD",
        final_result={
            "answer": "Đây là câu trả lời session 2",
            "evidence_list": [
                {
                    "evidence_id": "s2_ev1"
                }
            ],
            "structured_context": {
                "procedure_name": "CCCD"
            }
        }
    )

    context_1 = await get_context(
        session_1,
        "test"
    )

    context_2 = await get_context(
        session_2,
        "test"
    )

    print("\n===== SESSION 1 =====")

    print(
        json.dumps(
            context_1,
            ensure_ascii=False,
            indent=2
        )
    )

    print("\n===== SESSION 2 =====")

    print(
        json.dumps(
            context_2,
            ensure_ascii=False,
            indent=2
        )
    )

    print("\nSESSION_1_ID =", session_1)
    print("SESSION_2_ID =", session_2)


if __name__ == "__main__":
    asyncio.run(main())