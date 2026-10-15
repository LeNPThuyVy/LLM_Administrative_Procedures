import asyncio
import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.schemas.chat import ChatRequest
from backend.services.context_service import get_context, update_memory
from backend.services.ai_service import generate_answer, generate_answer_stream
from backend.services.queue_service import queue_manager

from domains import list_domains, is_valid_domain

router = APIRouter()

@router.get("/api/domains")
async def get_domains():
    return list_domains()


@router.post("/api/chat")
async def chat(request: ChatRequest):
    if not is_valid_domain(request.domain):
        raise HTTPException(
            status_code=400,
            detail=f"Domain không hợp lệ: {request.domain}"
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
                        async def _timed_update_multi():
                            t0 = time.time()
                            await update_memory(
                                session_id=request.session_id,
                                query=request.query,
                                final_result=final_result_data
                            )
                            print(f"[time] update_memory = {time.time() - t0:.2f}s")

                        asyncio.create_task(_timed_update_multi())
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
                    data = {
                        "question": result["clarification_question"]
                    }
                    yield (
                        "event: clarification\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )
                    yield (
                        "event: done\n"
                        f"data: {json.dumps({'needs_clarification': True}, ensure_ascii=False)}\n\n"
                    )

                    print(
                        f"[QUEUE] session={request.session_id} DONE"
                    )

                    async def _timed_update():
                        t0 = time.time()
                        await update_memory(
                            session_id=request.session_id,
                            query=request.query,
                            final_result=result
                        )
                        print(f"[time] update_memory = {time.time() - t0:.2f}s")

                    asyncio.create_task(_timed_update())
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

                async def _timed_update_done():
                    t0 = time.time()
                    await update_memory(
                        session_id=request.session_id,
                        query=request.query,
                        final_result=result
                    )
                    print(f"[time] update_memory = {time.time() - t0:.2f}s")

                asyncio.create_task(_timed_update_done())

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream"
    )