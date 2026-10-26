import asyncio

from fastapi.encoders import jsonable_encoder
from rag.pipeline import answer_query, answer_question_stream


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
    if isinstance(evidence_list, list) and response.domain:
        for c in evidence_list:
            if isinstance(c, dict) and "domain" not in c:
                c["domain"] = response.domain

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


async def generate_answer_stream(
    query: str,
    session_id: str,
    context: dict,
    domain: str | None = None
):
    """
    Streaming tokens trực tiếp từ llama-server SSE.
    Yields ('chunk', token_text) trong quá trình sinh,
    và cuối cùng yields ('final', result_dict).
    """
    loop = asyncio.get_running_loop()
    token_queue = asyncio.Queue()

    def on_token(token: str):
        loop.call_soon_threadsafe(token_queue.put_nowait, token)

    def run_pipeline():
        try:
            result = None

            for event in answer_question_stream(
                query=query,
                session_id=session_id,
                context=context,
                domain=domain,
            ):
                event_type = event.get("type")

                if event_type == "token":
                    token = event.get("text", "")
                    if token:
                        loop.call_soon_threadsafe(
                            token_queue.put_nowait,
                            token,
                        )

                elif event_type == "final":
                    result = event.get("response")

            loop.call_soon_threadsafe(
                token_queue.put_nowait,
                None,
            )
            return result

        except Exception as e:
            loop.call_soon_threadsafe(
                token_queue.put_nowait,
                e,
            )
            raise

    pipeline_task = asyncio.create_task(asyncio.to_thread(run_pipeline))

    while True:
        item = await token_queue.get()
        if item is None:
            break
        if isinstance(item, Exception):
            raise item
        yield ("chunk", item)

    response = await pipeline_task
    evidence_list = jsonable_encoder(response.claims)
    if isinstance(evidence_list, list) and response.domain:
        for c in evidence_list:
            if isinstance(c, dict) and "domain" not in c:
                c["domain"] = response.domain

    yield ("final", {
        "answer": response.answer or "",
        "evidence_list": evidence_list,
        "needs_clarification": response.needs_clarification,
        "clarification_question": response.clarification_question,
        "domain": response.domain,
        "mode": response.mode,
        "tool_calls": response.tool_calls,
    })