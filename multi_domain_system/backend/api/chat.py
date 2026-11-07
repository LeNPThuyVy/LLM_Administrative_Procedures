import json
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.schemas.chat import ChatRequest
from backend.services.context_service import get_context, schedule_memory_update
from backend.services.ai_service import generate_answer, generate_answer_stream
from backend.services.queue_service import queue_manager
from backend.api.sessions import USER_COOKIE_NAME
from backend.rate_limit import chat_rate_limiter
from backend.session_access import SessionAccessDenied, assert_session_access

from domains import list_domains, is_valid_domain

router = APIRouter()

@router.get("/api/domains")
async def get_domains():
    return list_domains()


@router.post("/api/chat")
@router.post("/api/chat/stream")
async def chat(request: ChatRequest, http_request: Request):
    client_key = http_request.client.host if http_request.client else "unknown"
    if not chat_rate_limiter.allow(client_key):
        raise HTTPException(
            status_code=429,
            detail="Bạn gửi quá nhiều câu hỏi. Vui lòng thử lại sau ít phút.",
            headers={"Retry-After": "60"},
        )

    if not is_valid_domain(request.domain):
        raise HTTPException(
            status_code=400,
            detail=f"Domain không hợp lệ: {request.domain}"
        )

    try:
        await assert_session_access(
            request.session_id,
            http_request.cookies.get(USER_COOKIE_NAME),
        )
    except SessionAccessDenied:
        raise HTTPException(
            status_code=403,
            detail="Không có quyền truy cập vào phiên này",
        )

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

                t_ctx = time.time()
                context = await get_context(
                    request.session_id,
                    request.query
                )
                print(f"[time] get_context = {time.time() - t_ctx:.2f}s")
                
                import my_config as cfg
                if getattr(cfg, "MULTI_INTENT_ENABLED", False):
                    from rag.multi.detector import detect_sub_queries
                    sub_queries, truncated = detect_sub_queries(request.query, context, request.domain)
                    if len(sub_queries) >= 2:
                        from rag.multi.orchestrator import answer_multi_stream
                        
                        final_result_data = {
                            "answer": "",
                            "evidence_list": [],
                            "needs_clarification": False,
                            "sections": []
                        }
                        
                        async for event_dict in answer_multi_stream(request.query, context, request.domain):
                            if event_dict["event"] == "section":
                                final_result_data["sections"].append(event_dict["data"])
                                # Cập nhật evidence list cho memory (gộp)
                                if "evidence_list" in event_dict["data"]:
                                    final_result_data["evidence_list"].extend(event_dict["data"]["evidence_list"])
                            elif event_dict["event"] == "done":
                                # Tự build answer tổng cho memory từ các section
                                parts = []
                                for sec in final_result_data["sections"]:
                                    parts.append(f"### {sec.get('title')}\n{sec.get('text')}")
                                final_result_data["answer"] = "\n\n".join(parts)
                                if truncated:
                                    final_result_data["answer"] += "\n\n(Lưu ý: Bạn đã hỏi quá nhiều thủ tục, hệ thống chỉ trả lời 8 thủ tục đầu tiên)."
                                    
                            yield (
                                f"event: {event_dict['event']}\n"
                                f"data: {json.dumps(event_dict['data'], ensure_ascii=False)}\n\n"
                            )
                            
                        # Cập nhật memory background
                        schedule_memory_update(
                            session_id=request.session_id,
                            query=request.query,
                            final_result=final_result_data,
                        )
                        print(f"[QUEUE] session={request.session_id} DONE (Multi)")
                        return

                result = None
                async for event_type, payload in generate_answer_stream(
                    query=request.query,
                    session_id=request.session_id,
                    context=context,
                    domain=request.domain
                ):
                    if event_type == "chunk":
                        yield (
                            "event: chunk\n"
                            f"data: {json.dumps({'text': payload}, ensure_ascii=False)}\n\n"
                        )
                    elif event_type == "final":
                        result = payload

                if not result:
                    return

                # Trường hợp cần clarification
                if result["needs_clarification"]:
                    clarification_text = (
                        result.get("clarification_question")
                        or result.get("answer")
                        or "Bạn muốn hỏi về nội dung nào? Vui lòng cung cấp thêm thông tin cụ thể để tôi có thể hỗ trợ bạn."
                    )
                    result["answer"] = clarification_text
                    data = {
                        "question": clarification_text
                    }
                    yield (
                        "event: clarification\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )
                    yield (
                        "event: done\n"
                        f"data: {json.dumps({'answer': clarification_text, 'evidence_list': [], 'needs_clarification': True}, ensure_ascii=False)}\n\n"
                    )

                    print(
                        f"[QUEUE] session={request.session_id} DONE"
                    )

                    schedule_memory_update(
                        session_id=request.session_id,
                        query=request.query,
                        final_result=result,
                    )
                    print(
                        f"[MEMORY] session={request.session_id} update scheduled"
                    )
                    return

                # Evidence (gửi sau hoặc trước khi stream)
                evidence_data = {
                    "evidence_list": result["evidence_list"]
                }
                yield (
                    "event: evidence\n"
                    f"data: {json.dumps(evidence_data, ensure_ascii=False)}\n\n"
                )

                # Done
                done_data = {
                    "answer": result["answer"],
                    "evidence_list": result["evidence_list"],
                    "needs_clarification": False,
                    "mode": result.get("mode")
                }
                yield (
                    "event: done\n"
                    f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"
                )

                print(
                    f"[QUEUE] session={request.session_id} DONE"
                )

                schedule_memory_update(
                    session_id=request.session_id,
                    query=request.query,
                    final_result=result,
                )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream"
    )