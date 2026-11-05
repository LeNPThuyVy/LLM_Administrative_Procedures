from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator

import my_config as cfg
from backend.schemas.chat import ChatRequest
from backend.services.ai_service import generate_answer_stream
from backend.services.background_tasks import run_background_with_retry
from backend.services.context_service import get_context, update_memory
from backend.services.queue_service import queue_manager

logger = logging.getLogger(__name__)


async def stream_chat_events(request: ChatRequest) -> AsyncGenerator[str, None]:
    """
    Business service executing chat workflow:
    - Queue classification and concurrency gating.
    - Context retrieval.
    - Multi-intent and single-intent RAG generation.
    - Event formatting for SSE transport.
    - Reliable background memory persistence.
    """
    session_lock = queue_manager.get_session_lock(request.session_id)

    async with session_lock:
        async with queue_manager.semaphore:
            request_type = queue_manager.classify_request(request.query)
            logger.info(
                "[QUEUE] session=%s type=%s START",
                request.session_id,
                request_type,
            )

            t_ctx = time.time()
            context = await get_context(
                request.session_id,
                request.query,
            )
            logger.info("[time] get_context = %.2fs", time.time() - t_ctx)

            # 1. Multi-intent flow
            if getattr(cfg, "MULTI_INTENT_ENABLED", False):
                from rag.multi.detector import detect_sub_queries
                sub_queries, truncated = detect_sub_queries(request.query, context, request.domain)
                if len(sub_queries) >= 2:
                    from rag.multi.orchestrator import answer_multi_stream

                    final_result_data = {
                        "answer": "",
                        "evidence_list": [],
                        "needs_clarification": False,
                        "sections": [],
                    }

                    async for event_dict in answer_multi_stream(request.query, context, request.domain):
                        if event_dict["event"] == "section":
                            final_result_data["sections"].append(event_dict["data"])
                            if "evidence_list" in event_dict["data"]:
                                final_result_data["evidence_list"].extend(event_dict["data"]["evidence_list"])
                        elif event_dict["event"] == "done":
                            parts = []
                            for sec in final_result_data["sections"]:
                                parts.append(f"### {sec.get('title')}\n{sec.get('text')}")
                            final_result_data["answer"] = "\n\n".join(parts)
                            if truncated:
                                final_result_data["answer"] += (
                                    "\n\n(Lưu ý: Bạn đã hỏi quá nhiều thủ tục, "
                                    "hệ thống chỉ trả lời 8 thủ tục đầu tiên)."
                                )

                        yield (
                            f"event: {event_dict['event']}\n"
                            f"data: {json.dumps(event_dict['data'], ensure_ascii=False)}\n\n"
                        )

                    # Background memory update with retry
                    run_background_with_retry(
                        update_memory,
                        session_id=request.session_id,
                        query=request.query,
                        final_result=final_result_data,
                        name=f"update_memory_multi_{request.session_id[:8]}",
                    )
                    logger.info("[QUEUE] session=%s DONE (Multi)", request.session_id)
                    return

            # 2. Single-intent flow
            result = None
            async for event_type, payload in generate_answer_stream(
                query=request.query,
                session_id=request.session_id,
                context=context,
                domain=request.domain,
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

            # Case: needs clarification
            if result.get("needs_clarification"):
                clarification_text = (
                    result.get("clarification_question")
                    or result.get("answer")
                    or "Bạn muốn hỏi về nội dung nào? Vui lòng cung cấp thêm thông tin cụ thể để tôi có thể hỗ trợ bạn."
                )
                result["answer"] = clarification_text
                data = {"question": clarification_text}

                yield (
                    "event: clarification\n"
                    f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                )
                yield (
                    "event: done\n"
                    f"data: {json.dumps({'answer': clarification_text, 'evidence_list': [], 'needs_clarification': True}, ensure_ascii=False)}\n\n"
                )

                run_background_with_retry(
                    update_memory,
                    session_id=request.session_id,
                    query=request.query,
                    final_result=result,
                    name=f"update_memory_clarification_{request.session_id[:8]}",
                )
                logger.info("[QUEUE] session=%s DONE (Clarification)", request.session_id)
                return

            # Case: successful answer
            evidence_data = [
                {
                    "source": ev.source,
                    "title": ev.title,
                    "candidate_id": ev.candidate_id,
                    "document_id": ev.document_id,
                    "source_url": ev.source_url,
                }
                for ev in result.get("evidence_candidates", [])
            ]

            if evidence_data:
                yield (
                    "event: evidence\n"
                    f"data: {json.dumps({'evidence_list': evidence_data}, ensure_ascii=False)}\n\n"
                )

            done_data = {
                "answer": result.get("answer", ""),
                "evidence_list": evidence_data,
                "needs_clarification": False,
            }
            if result.get("mode"):
                done_data["mode"] = result["mode"]

            yield (
                "event: done\n"
                f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"
            )

            run_background_with_retry(
                update_memory,
                session_id=request.session_id,
                query=request.query,
                final_result=result,
                name=f"update_memory_normal_{request.session_id[:8]}",
            )
            logger.info("[QUEUE] session=%s DONE", request.session_id)

