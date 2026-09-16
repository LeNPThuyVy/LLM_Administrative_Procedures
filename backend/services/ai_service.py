import asyncio


async def generate_answer(query: str, context: dict):
    await asyncio.sleep(0.3)

    evidence_list = [
        {
            "source_id": "1",
            "title": "Tài liệu demo",
            "snippet": "Đây là evidence mock phục vụ test."
        }
    ]

    answer = f"Câu trả lời demo cho câu hỏi: {query}"

    return {
        "answer": answer,
        "evidence_list": evidence_list,
        "needs_clarification": False,
        "clarification_question": None
    }