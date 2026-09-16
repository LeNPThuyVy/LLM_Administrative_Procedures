import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from schemas.chat import ChatRequest
from services.context_service import get_context
from services.ai_service import generate_answer
from services.queue_service import queue_manager


router = APIRouter()


@router.post("/api/chat")
async def chat(request: ChatRequest):

    async def event_stream():

        session_lock = queue_manager.get_session_lock(
            request.session_id
        )

        async with session_lock:
            async with queue_manager.semaphore:

                request_type = queue_manager.classify_request(
                    request.query
                )

                print(
                    f"[QUEUE] session={request.session_id} "
                    f"type={request_type} START"
                )

                context = await get_context(
                    request.session_id,
                    request.query
                )

                result = await generate_answer(
                    request.query,
                    context
                )

                # Nếu cần hỏi lại
                if result["needs_clarification"]:
                    data = {
                        "question":
                            result["clarification_question"]
                    }

                    yield (
                        "event: clarification\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )

                    yield (
                        "event: done\n"
                        'data: {"needs_clarification": true}\n\n'
                    )

                    print(
                        f"[QUEUE] session={request.session_id} DONE"
                    )

                    return

                # Evidence
                evidence_data = {
                    "evidence_list":
                        result["evidence_list"]
                }

                yield (
                    "event: evidence\n"
                    f"data: {json.dumps(evidence_data, ensure_ascii=False)}\n\n"
                )

                # Stream answer
                for word in result["answer"].split():
                    yield (
                        "event: chunk\n"
                        f"data: {json.dumps({'text': word + ' '}, ensure_ascii=False)}\n\n"
                    )

                    await asyncio.sleep(0.3)

                # Done
                done_data = {
                    "answer": result["answer"],
                    "evidence_list":
                        result["evidence_list"],
                    "needs_clarification": False
                }

                yield (
                    "event: done\n"
                    f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"
                )

                print(
                    f"[QUEUE] session={request.session_id} DONE"
                )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream"
    )