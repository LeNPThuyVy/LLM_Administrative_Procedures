from __future__ import annotations

import logging
from collections.abc import Callable
from queue import Queue
from threading import Thread

from domains.runtime import get_domain_runtime
from guardrails.risk import classify_risk, resolve_mode
from rag.generator import generate_answer_1_5b, generate_answer_3b, stream_answer_3b
from rag.mapper import AnswerResponse
from rag.pipeline_guards import extract_text

logger = logging.getLogger(__name__)


def answer_question_stream(
    query: str,
    session_id: str | None = None,
    context: dict | None = None,
    domain: str | None = None,
    synthesizer_generator: Callable[[str], str] = generate_answer_1_5b,
    stream_generator=stream_answer_3b,
):
    """
    Streaming entry point của AI Core.

    Events:
    - {"type": "token", "text": "..."}
    - {"type": "final", "response": AnswerResponse}

    Strict / high-risk:
        chạy full pipeline + verification trước,
        sau đó mới phát nội dung đã kiểm tra.

    Friendly:
        stream token trực tiếp trong lúc model generate,
        sau đó phát final AnswerResponse.

    session_id và context vẫn được truyền đầy đủ nên
    không làm mất multi-turn / tải hội thoại.
    """
    from rag.pipeline import answer_query

    if isinstance(query, (list, dict)):
        normalized_query = extract_text(query)
    elif not isinstance(query, str):
        normalized_query = str(query) if query is not None else ""
    else:
        normalized_query = query

    runtime = get_domain_runtime(domain)

    domain_risk_kw = getattr(runtime.config, "risk_keywords", None) if hasattr(runtime, "config") else None
    risk_result = classify_risk(
        normalized_query,
        domain_risk_keywords=domain_risk_kw,
    )

    effective_mode = resolve_mode(
        runtime.mode,
        risk_result,
    )

    # ---------------------------------------------------------
    # STRICT / HIGH-RISK
    # Không phát token chưa verification.
    # ---------------------------------------------------------
    if effective_mode == "strict":
        result = answer_query(
            query=normalized_query,
            session_id=session_id,
            context=context,
            domain=runtime.domain_id,
            generator=generate_answer_3b,
            synthesizer_generator=synthesizer_generator,
        )

        if result.answer:
            for token in result.answer.split():
                yield {
                    "type": "token",
                    "text": token + " ",
                }

        yield {
            "type": "final",
            "response": result,
        }
        return

    # ---------------------------------------------------------
    # FRIENDLY FAST STREAM
    # ---------------------------------------------------------
    event_queue = Queue()

    state = {
        "result": None,
        "error": None,
        "streamed": False,
    }

    def streaming_answer_generator(prompt: str) -> str:
        parts: list[str] = []

        for token in stream_generator(prompt):
            if not token:
                continue

            parts.append(token)
            state["streamed"] = True

            event_queue.put(
                (
                    "token",
                    token,
                )
            )

        return "".join(parts)

    def worker():
        try:
            state["result"] = answer_query(
                query=normalized_query,
                session_id=session_id,
                context=context,
                domain=runtime.domain_id,
                generator=streaming_answer_generator,
                synthesizer_generator=synthesizer_generator,
            )
        except Exception as exc:
            logger.exception("[streaming] Error in background stream worker: %s", exc)
            state["error"] = exc
        finally:
            event_queue.put(("done", None))

    thread = Thread(
        target=worker,
        daemon=True,
    )
    thread.start()

    while True:
        event_type, payload = event_queue.get()

        if event_type == "token":
            yield {
                "type": "token",
                "text": payload,
            }
            continue

        if event_type == "done":
            break

    thread.join()

    if state["error"] is not None:
        raise state["error"]

    result = state["result"]

    if result is None:
        result = AnswerResponse(
            answer="",
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=runtime.domain_id,
            mode=effective_mode,
            tool_calls=[],
        )

    # Trường hợp pipeline kết thúc trước generation, ví dụ clarification/no-evidence/input guard.
    if not state["streamed"] and result.answer:
        yield {
            "type": "token",
            "text": result.answer,
        }

    yield {
        "type": "final",
        "response": result,
    }
