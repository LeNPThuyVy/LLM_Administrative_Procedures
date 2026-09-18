import asyncio
import json
import uuid

from context.context_service import (
    update_memory,
    get_context
)


SESSION_ID = "34398793-cba5-4d9d-ac7a-7773035e3284"


async def main():
    session_id = uuid.UUID(SESSION_ID)

    final_result = {
        "answer": (
            "Bạn cần chuẩn bị CCCD và "
            "các giấy tờ liên quan."
        ),

        "evidence_list": [
            {
                "evidence_id": "ev_001",
                "article": "Điều 5",
                "clause": "Khoản 2",
                "retrieval_score": 0.91,
                "rerank_score": 0.95
            }
        ],

        "structured_context": {
            "procedure_name": "Đăng ký thường trú",
            "location": "TP.HCM",
            "intent": "hỏi thành phần hồ sơ"
        }
    }

    await update_memory(
        session_id=session_id,
        query="Tôi cần chuẩn bị giấy tờ gì?",
        final_result=final_result
    )

    print("update_memory OK")

    context = await get_context(
        session_id=session_id,
        query="test"
    )

    print(
        json.dumps(
            context,
            ensure_ascii=False,
            indent=2
        )
    )


if __name__ == "__main__":
    asyncio.run(main())