import asyncio
import json
from backend.services.rate_limit_service import (
    rate_limiter,
    RateLimitExceeded,
)
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.schemas.chat import ChatRequest
from backend.services.context_service import (
    get_context,
    update_memory,
)
from backend.services.ai_service import generate_answer
from backend.services.queue_service import (
    queue_manager,
    QueueFullError,
    QueueTimeoutError,
)

from domains import list_domains, is_valid_domain


router = APIRouter()


@router.get("/api/domains")
async def get_domains():
    return list_domains()


@router.post("/api/chat")
async def chat(
    request: ChatRequest,
    http_request: Request,
):
    if not is_valid_domain(request.domain):
        raise HTTPException(
            status_code=400,
            detail=f"Domain không hợp lệ: {request.domain}",
        )
    client_ip = (
        http_request.client.host
        if http_request.client
        else "unknown"
    )

    try:
        await rate_limiter.check(
            session_id=request.session_id,
            ip_address=client_ip,
        )

    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": 429,
                "message":
                    "Bạn gửi yêu cầu quá nhanh. "
                    "Vui lòng thử lại sau.",
                "scope": exc.scope,
                "retry_after": exc.retry_after,
            },
            headers={
                "Retry-After": str(exc.retry_after),
            },
        )
    async def event_stream():
        try:
            async with queue_manager.session_scope(
                request.session_id
            ):

                # Chỉ giữ semaphore trong lúc xử lý AI.
                async with queue_manager.execution_slot():
                    request_type = (
                        queue_manager.classify_request(
                            request.query
                        )
                    )

                    print(
                        f"[QUEUE] session={request.session_id} "
                        f"type={request_type} START"
                    )

                    context = await get_context(
                        request.session_id,
                        request.query,
                    )

                    result = await generate_answer(
                        query=request.query,
                        session_id=request.session_id,
                        context=context,
                        domain=request.domain,
                    )

                # ==========================================
                # Từ đây semaphore đã được release.
                # Chỉ còn gửi dữ liệu về client.
                # ==========================================

                # Clarification
                if result["needs_clarification"]:
                    data = {
                        "question":
                            result["clarification_question"]
                    }

                    yield (
                        "event: clarification\n"
                        f"data: "
                        f"{json.dumps(data, ensure_ascii=False)}"
                        "\n\n"
                    )

                    done_data = {
                        "needs_clarification": True,
                    }

                    yield (
                        "event: done\n"
                        f"data: "
                        f"{json.dumps(done_data, ensure_ascii=False)}"
                        "\n\n"
                    )

                    print(
                        f"[QUEUE] "
                        f"session={request.session_id} DONE"
                    )

                    asyncio.create_task(
                        update_memory(
                            session_id=request.session_id,
                            query=request.query,
                            final_result=result,
                        )
                    )

                    print(
                        f"[MEMORY] "
                        f"session={request.session_id} "
                        f"update scheduled"
                    )

                    return

                # Evidence
                evidence_data = {
                    "evidence_list":
                        result["evidence_list"]
                }

                yield (
                    "event: evidence\n"
                    f"data: "
                    f"{json.dumps(evidence_data, ensure_ascii=False)}"
                    "\n\n"
                )

                # Streaming giả hiện tại.
                # Sẽ nối streaming thật sau khi B cung cấp
                # answer_question_stream().
                for word in result["answer"].split():
                    chunk_data = {
                        "text": word + " ",
                    }

                    yield (
                        "event: chunk\n"
                        f"data: "
                        f"{json.dumps(chunk_data, ensure_ascii=False)}"
                        "\n\n"
                    )

                    await asyncio.sleep(0.05)

                # Done
                done_data = {
                    "answer": result["answer"],
                    "evidence_list":
                        result["evidence_list"],
                    "needs_clarification": False,
                }

                yield (
                    "event: done\n"
                    f"data: "
                    f"{json.dumps(done_data, ensure_ascii=False)}"
                    "\n\n"
                )

                print(
                    f"[QUEUE] "
                    f"session={request.session_id} DONE"
                )

                # Update memory chạy nền,
                # không block client.
                asyncio.create_task(
                    update_memory(
                        session_id=request.session_id,
                        query=request.query,
                        final_result=result,
                    )
                )

                print(
                    f"[MEMORY] "
                    f"session={request.session_id} "
                    f"update scheduled"
                )

        except QueueFullError:
            error_data = {
                "code": 429,
                "message":
                    "Hệ thống đang quá tải. "
                    "Vui lòng thử lại sau.",
            }

            yield (
                "event: error\n"
                f"data: "
                f"{json.dumps(error_data, ensure_ascii=False)}"
                "\n\n"
            )

        except QueueTimeoutError:
            error_data = {
                "code": 429,
                "message":
                    "Yêu cầu chờ quá lâu. "
                    "Vui lòng thử lại sau.",
            }

            yield (
                "event: error\n"
                f"data: "
                f"{json.dumps(error_data, ensure_ascii=False)}"
                "\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )