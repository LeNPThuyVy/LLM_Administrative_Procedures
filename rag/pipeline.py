import asyncio
import re

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from queue import Queue
from threading import Thread

import my_config as cfg

from domains.runtime import get_domain_runtime
from guardrails.input import (
    mask_sensitive_for_log,
    validate_input,
)
from guardrails.output import apply_output_guard
from guardrails.risk import classify_risk, resolve_mode
from mcp_layer.bridge import run_tools
from rag.evidence_builder import build_evidence_candidates
from rag.generator import (
    generate_answer_1_5b,
    generate_answer_3b,
    stream_answer_3b,
)
from rag.history_reader import history_reader
from rag.mapper import AnswerResponse, map_verification_results
from rag.procedure_reader import procedure_reader
from rag.prompt_builder import build_prompt
from rag.rerank import rerank
from rag.retrieval import retrieve, retrieve_two_step
from rag.synthesizer import synthesizer
from rag.verification import verify_answer


FALLBACK_TEXT = (
    "Thông tin trong tài liệu được cung cấp "
    "chưa đủ để trả lời câu hỏi này."
)


# Returned when user references a location outside the HCMC dataset (Issue #7).
LOCATION_NOT_SUPPORTED_TEXT = (
    "Hiện tại hệ thống chỉ hỗ trợ thông tin thủ tục hành chính tại "
    "Thành phố Hồ Chí Minh. Địa điểm bạn hỏi chưa có trong cơ sở dữ liệu."
)


# Vietnamese location terms that are definitely NOT HCMC.
# Keep this list to cases clearly outside the dataset.
_NON_HCMC_PATTERNS = re.compile(
    r"\b(bình dương|bình phước|đồng nai|long an|tây ninh|"
    r"bà rịa|vũng tàu|tiền giang|cần thơ|hà nội|đà nẵng|"
    r"hải phòng|huế|nha trang|đà lạt|quy nhơn|vinh|"
    r"hải dương|nam định|ninh bình)\b",
    re.IGNORECASE | re.UNICODE,
)


def _extract_text(val: object) -> str:
    """Safely extract string text from string, list, or dict message content."""
    if isinstance(val, str):
        return val

    if isinstance(val, list):
        return " ".join(
            _extract_text(item)
            for item in val
            if item
        )

    if isinstance(val, dict):
        if "text" in val and isinstance(val["text"], str):
            return val["text"]

        if "content" in val:
            return _extract_text(val["content"])

        return " ".join(
            _extract_text(v)
            for v in val.values()
            if v
        )

    return str(val) if val is not None else ""


def _detect_unsupported_location(text: str) -> bool:
    """
    Return True if text contains a Vietnamese location that is
    explicitly NOT in the HCMC dataset.

    Only triggers for well-known non-HCMC cities / provinces
    to avoid false positives.
    """
    return bool(
        _NON_HCMC_PATTERNS.search(text)
    )


def _answer_from_evidence(
    evidence_candidates,
    field_types: list[str] | None = None,
):
    """
    Nếu LLM không tạo được câu trả lời hữu ích,
    dùng trực tiếp evidence tốt nhất có chứa thông tin cần tìm.
    """
    if not evidence_candidates:
        return FALLBACK_TEXT

    # Nếu chỉ cần docs, tìm chunk có chứa "Thành phần hồ sơ:"
    if (
        field_types
        and "docs" in field_types
        and len(field_types) == 1
    ):
        for ev in evidence_candidates:
            content = (ev.content or "").strip()

            if "Thành phần hồ sơ:" in content:
                docs_part = content.split(
                    "Thành phần hồ sơ:",
                    1,
                )[1]

                return (
                    "Thành phần hồ sơ:\n"
                    f"{docs_part.strip()} "
                    f"[{ev.candidate_id}]"
                )

    # Nếu không filter được hoặc filter thất bại,
    # trả về các chunk phù hợp.
    parts = []
    seen_titles = set()

    # Ưu tiên chunk general.
    general_docs = {
        ev.document_id
        for ev in evidence_candidates
        if (
            ev.chunk_id
            and ev.chunk_id.endswith("_general")
        )
    }

    for ev in evidence_candidates:
        # Nếu doc này đã có general chunk,
        # bỏ qua các chunk con.
        if (
            ev.document_id in general_docs
            and not (
                ev.chunk_id
                and ev.chunk_id.endswith("_general")
            )
        ):
            continue

        content = (ev.content or "").strip()

        if not content:
            continue

        # Xử lý dòng Tên thủ tục để tránh lặp.
        title_match = re.search(
            r"^Tên thủ tục: (.*?)\n",
            content,
        )

        if title_match:
            title = title_match.group(1).strip()

            if title not in seen_titles:
                parts.append(
                    f"Tên thủ tục: {title}"
                )
                seen_titles.add(title)

            content = content.replace(
                title_match.group(0),
                "",
            ).strip()

        if content:
            parts.append(
                f"{content} [{ev.candidate_id}]"
            )

    if parts:
        return "\n\n".join(parts)

    return FALLBACK_TEXT


def _is_useless_answer(answer: str) -> bool:
    """
    Kiểm tra câu trả lời rỗng, chỉ có citation,
    hoặc quá ngắn.
    """
    if not answer or not answer.strip():
        return True

    text = answer.strip()

    if (
        text.lower().strip()
        == FALLBACK_TEXT.lower().strip()
    ):
        return True

    citation_only = re.fullmatch(
        r"\s*\[?EC_\d{3}\]?\s*[.!]?\s*",
        text,
        flags=re.IGNORECASE,
    )

    if citation_only:
        return True

    cleaned = re.sub(
        r"\[?EC_\d{3}\]?",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    if len(cleaned) < 15:
        return True

    return False


def _run_tools_sync(
    query: str,
    runtime,
    context: dict | None,
):
    """
    Gọi async MCP từ pipeline sync.

    Nếu đang ở trong event loop của FastAPI/WebSocket,
    chạy coroutine trong thread riêng.
    """

    async def _runner():
        return await run_tools(
            query=query,
            runtime=runtime,
            context=context,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_runner())

    with ThreadPoolExecutor(
        max_workers=1
    ) as executor:
        future = executor.submit(
            lambda: asyncio.run(_runner())
        )

        return future.result(
            timeout=10
        )


def _build_tool_calls(
    tool_evidence,
) -> list[dict]:
    """
    Convert MCP evidence thành metadata tool_calls
    để backend/UI có thể trả về client.
    """
    return [
        {
            "tool": ev.source.removeprefix(
                "tool:"
            ),
            "candidate_id": ev.candidate_id,
            "document_id": ev.document_id,
            "source_url": ev.source_url,
        }
        for ev in tool_evidence
        if (
            getattr(
                ev,
                "source",
                "",
            ).startswith("tool:")
        )
    ]


def answer_query(
    query: str,
    session_id: str | None = None,
    context: dict | None = None,
    domain: str | None = None,
    generator: Callable[[str], str] = generate_answer_3b,
    synthesizer_generator: Callable[[str], str] = generate_answer_1_5b,
) -> AnswerResponse:
    """
    Run the complete AI Core / RAG pipeline.
    """
    _ = session_id

    # ---------------------------------------------------------
    # Normalize input
    # ---------------------------------------------------------
    if isinstance(query, (list, dict)):
        query = _extract_text(query)

    elif not isinstance(query, str):
        query = (
            str(query)
            if query is not None
            else ""
        )

    # ---------------------------------------------------------
    # Input guardrail
    # ---------------------------------------------------------
    input_guard = validate_input(query)

    if not input_guard.allowed:
        print(
            "[guardrail] Blocked input: "
            f"{input_guard.reason} | "
            f"{mask_sensitive_for_log(query)}"
        )

        return AnswerResponse(
            answer=(
                "Yêu cầu này không thể được xử lý "
                "vì vi phạm quy tắc an toàn."
            ),
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            tool_calls=[],
        )

    if not query or not query.strip():
        return AnswerResponse(
            answer="",
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            tool_calls=[],
        )

    if context is None:
        context = {}

    # ---------------------------------------------------------
    # Layer 2 - Domain runtime + risk classifier
    # ---------------------------------------------------------
    runtime = get_domain_runtime(domain)
    domain = runtime.domain_id

    risk_result = classify_risk(query)

    effective_mode = resolve_mode(
        runtime.mode,
        risk_result,
    )

    # ---------------------------------------------------------
    # GĐ1 fix — Out-of-scope location detection
    #
    # Giữ nguyên logic cũ của nhóm.
    # Chỉ kiểm tra user message hiện tại.
    # ---------------------------------------------------------
    if _detect_unsupported_location(query):
        print(
            "[pipeline] Unsupported location "
            f"in current query: {query[:100]!r}"
        )

        return AnswerResponse(
            answer=LOCATION_NOT_SUPPORTED_TEXT,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
            tool_calls=[],
        )

    # ---------------------------------------------------------
    # Multi-agent preprocessing
    # ---------------------------------------------------------

    # 1. Read conversation history.
    history = history_reader(
        context
    )

    # 2. Retrieve lightweight procedure/topic hints.
    procedure_hint = procedure_reader(
        query=query,
        context=context,
        top_k=2,
    )

    # 3. Synthesize current query using history.
    consolidated = synthesizer(
        query=query,
        history=history,
        procedure_hint=procedure_hint,
        generator=synthesizer_generator,
        domain=domain,
    )

    # ---------------------------------------------------------
    # Clarification branch
    # ---------------------------------------------------------
    if consolidated.needs_clarification:
        return AnswerResponse(
            answer=None,
            claims=[],
            needs_clarification=True,
            clarification_question=(
                consolidated.clarification_question
            ),
            domain=domain,
            mode=effective_mode,
            tool_calls=[],
        )

    # ---------------------------------------------------------
    # MCP tools
    # ---------------------------------------------------------
    tool_evidence = []

    try:
        # Risk classifier có thể nâng friendly -> strict.
        # Dùng bản copy runtime, không sửa runtime gốc.
        tool_runtime = replace(
            runtime,
            mode=effective_mode,
        )

        tool_evidence = _run_tools_sync(
            query=consolidated.resolved_query,
            runtime=tool_runtime,
            context=context,
        )

    except Exception as exc:
        # MCP failure không được làm hỏng normal RAG.
        print(
            "[pipeline] MCP tools unavailable: "
            f"{exc}"
        )
        tool_evidence = []

    tool_calls = _build_tool_calls(
        tool_evidence
    )

    # ---------------------------------------------------------
    # Official RAG pipeline
    # ---------------------------------------------------------

    # 1. Two-step retrieval.
    retrieved_chunks = retrieve_two_step(
        query=consolidated.resolved_query,
        context=context,
        domain=domain,
    )

    # Nếu không có RAG evidence lẫn MCP evidence.
    if (
        not retrieved_chunks
        and not tool_evidence
    ):
        return AnswerResponse(
            answer=None,
            claims=[],
            needs_clarification=True,
            clarification_question=(
                "Bạn muốn hỏi về thủ tục hành chính nào cụ thể? "
                "Vui lòng nêu tên thủ tục để tôi có thể "
                "hỗ trợ chính xác hơn."
            ),
            domain=domain,
            mode=effective_mode,
            tool_calls=tool_calls,
        )

    # ---------------------------------------------------------
    # Strict relevance threshold
    #
    # Khi Person A expose raw_score, pipeline tự ưu tiên
    # raw cosine. Trong thời gian chưa có raw_score,
    # fallback retrieval_score để giữ backward compatibility.
    #
    # MCP-only evidence không bị chặn ở gate này.
    # ---------------------------------------------------------
    top_score = None

    if retrieved_chunks:
        first_chunk = retrieved_chunks[0]

        top_score = getattr(
            first_chunk,
            "raw_score",
            first_chunk.retrieval_score,
        )

    if (
        effective_mode == "strict"
        and top_score is not None
        and top_score
        < runtime.min_retrieval_score
    ):
        print(
            "[pipeline] Strict mode: "
            f"Top-1 score {top_score:.3f} < "
            f"{runtime.min_retrieval_score:.3f} "
            "-> NO EVIDENCE"
        )

        answer = (
            runtime.no_evidence_message
            or FALLBACK_TEXT
        )

        if runtime.disclaimer:
            answer = (
                f"{answer}\n\n"
                f"{runtime.disclaimer}"
            )

        return AnswerResponse(
            answer=answer,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
            tool_calls=tool_calls,
        )

    # ---------------------------------------------------------
    # 2. Rerank
    # ---------------------------------------------------------
    ranked_chunks = (
        rerank(retrieved_chunks)
        if retrieved_chunks
        else []
    )

    # ---------------------------------------------------------
    # 3. Build evidence
    # ---------------------------------------------------------
    evidence_candidates = (
        build_evidence_candidates(
            ranked_chunks
        )
    )

    # MCP evidence đi chung vào prompt + verification.
    evidence_candidates.extend(
        tool_evidence
    )

    if (
        not evidence_candidates
        and effective_mode == "strict"
    ):
        answer = (
            runtime.no_evidence_message
            or FALLBACK_TEXT
        )

        if runtime.disclaimer:
            answer = (
                f"{answer}\n\n"
                f"{runtime.disclaimer}"
            )

        return AnswerResponse(
            answer=answer,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
            tool_calls=tool_calls,
        )

    # ---------------------------------------------------------
    # 4. Prompt Builder
    # ---------------------------------------------------------
    prompt = build_prompt(
        query=consolidated.resolved_query,
        evidence_candidates=evidence_candidates,
        context=context,
        domain=domain,
    )

    # ---------------------------------------------------------
    # 5. Final Answer Generation
    # ---------------------------------------------------------
    from rag.generator import LLMUnavailableError

    try:
        generated_answer = generator(
            prompt
        )

    except LLMUnavailableError as exc:
        print(
            f"GENERATOR ERROR: {exc}"
        )

        return AnswerResponse(
            answer=(
                "Hệ thống đang bận, "
                "vui lòng thử lại sau ít phút."
            ),
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
            tool_calls=tool_calls,
        )

    except Exception as exc:
        print(
            "GENERATOR ERROR:",
            repr(exc),
        )
        generated_answer = ""

    # ---------------------------------------------------------
    # 6. Fallback if useless answer
    # ---------------------------------------------------------
    if _is_useless_answer(
        generated_answer
    ):
        from rag.prompt_builder import (
            _detect_field_types,
        )

        field_types = _detect_field_types(
            consolidated.resolved_query
        )

        generated_answer = (
            _answer_from_evidence(
                evidence_candidates,
                field_types,
            )
        )

    # ---------------------------------------------------------
    # 7. Verification
    # ---------------------------------------------------------
    verification_results = verify_answer(
        generated_answer=generated_answer,
        evidence_candidates=evidence_candidates,
    )

    # ---------------------------------------------------------
    # 8. Mapper
    # ---------------------------------------------------------
    verified_claims = (
        map_verification_results(
            verification_results=verification_results,
            evidence_candidates=evidence_candidates,
        )
    )

    # Strict: answer phải có evidence-supported claim.
    if (
        effective_mode == "strict"
        and not verified_claims
    ):
        answer = (
            runtime.no_evidence_message
            or FALLBACK_TEXT
        )

        if runtime.disclaimer:
            answer = (
                f"{answer}\n\n"
                f"{runtime.disclaimer}"
            )

        return AnswerResponse(
            answer=answer,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
            tool_calls=tool_calls,
        )

    # ---------------------------------------------------------
    # Output guardrail
    # ---------------------------------------------------------
    generated_answer = apply_output_guard(
        generated_answer,
        effective_mode,
        runtime.disclaimer,
        allowed_text=" ".join(
            ev.content or ""
            for ev in evidence_candidates
        ),
    )

    # ---------------------------------------------------------
    # Final response
    # ---------------------------------------------------------
    return AnswerResponse(
        answer=generated_answer,
        claims=verified_claims,
        needs_clarification=False,
        clarification_question=None,
        domain=domain,
        mode=effective_mode,
        tool_calls=tool_calls,
    )


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

    # ---------------------------------------------------------
    # Normalize query giống answer_query()
    # ---------------------------------------------------------
    if isinstance(query, (list, dict)):
        normalized_query = (
            _extract_text(query)
        )

    elif not isinstance(query, str):
        normalized_query = (
            str(query)
            if query is not None
            else ""
        )

    else:
        normalized_query = query

    runtime = get_domain_runtime(
        domain
    )

    risk_result = classify_risk(
        normalized_query
    )

    effective_mode = resolve_mode(
        runtime.mode,
        risk_result,
    )

    # ---------------------------------------------------------
    # STRICT / HIGH-RISK
    #
    # Không phát token chưa verification.
    # ---------------------------------------------------------
    if effective_mode == "strict":
        result = answer_query(
            query=normalized_query,
            session_id=session_id,
            context=context,
            domain=runtime.domain_id,
            generator=generate_answer_3b,
            synthesizer_generator=(
                synthesizer_generator
            ),
        )

        if result.answer:
            for token in (
                result.answer.split()
            ):
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

    def streaming_answer_generator(
        prompt: str,
    ) -> str:
        """
        Adapter để answer_query() vẫn nhận generator
        Callable[[str], str], nhưng token được đẩy ra
        queue ngay khi model sinh.
        """
        parts: list[str] = []

        for token in stream_generator(
            prompt
        ):
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
                generator=(
                    streaming_answer_generator
                ),
                synthesizer_generator=(
                    synthesizer_generator
                ),
            )

        except Exception as exc:
            state["error"] = exc

        finally:
            event_queue.put(
                (
                    "done",
                    None,
                )
            )

    thread = Thread(
        target=worker,
        daemon=True,
    )

    thread.start()

    while True:
        event_type, payload = (
            event_queue.get()
        )

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

    # Trường hợp pipeline kết thúc trước generation,
    # ví dụ clarification/no-evidence/input guard.
    if (
        not state["streamed"]
        and result.answer
    ):
        yield {
            "type": "token",
            "text": result.answer,
        }

    yield {
        "type": "final",
        "response": result,
    }