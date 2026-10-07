import asyncio

from fastapi.encoders import jsonable_encoder
from rag.pipeline import answer_query


async def generate_answer(
    query: str,
    session_id: str,
    context: dict,
    domain: str | None = None
):
    response = await asyncio.to_thread(
        answer_query,
        query,
        session_id,
        context,
        domain
    )

    # Chuyển các object Pydantic / Citation / nested objects
    # thành dữ liệu JSON serializable.
    evidence_list = jsonable_encoder(
        response.claims
    )

    return {
        "answer": response.answer or "",
        "evidence_list": evidence_list,
        "needs_clarification": (
            response.needs_clarification
        ),
        "clarification_question": (
            response.clarification_question
        ),
        "domain": response.domain,
        "mode": response.mode,
        "tool_calls": response.tool_calls,
    }