import asyncio
import re
import time
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
    """Nếu LLM không tạo được câu trả lời hữu ích,
    dùng trực tiếp evidence tốt nhất có chứa thông tin cần tìm."""
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
        if (ev.chunk_id and ev.chunk_id.endswith("_general"))
    }

    for ev in evidence_candidates:
        # Nếu doc này đã có general chunk,
        # bỏ qua các chunk con.
        if (
            ev.document_id in general_docs
            and not (ev.chunk_id and ev.chunk_id.endswith("_general"))
        ):
            continue

        content = (ev.content or "").strip()

        if not content:
            continue

        # Xử lý dòng Tên thủ tục để tránh lặp.
        title_match = re.search(
            r"^Tên thủ tục: (.*?)\\n",
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

_PIPELINE_ANSWER_CACHE: dict[tuple, AnswerResponse] = {}
_MAX_ANSWER_CACHE_SIZE = 500

def _get_cache_key(query: str, context: dict | None, domain: str | None, session_id: str | None = None) -> tuple:
    q_norm = (query or "").strip().lower()
    proc = ""
    if context:
        sc = context.get("structured_context") or context.get("long_term_memory") or {}
        if isinstance(sc, dict):
            proc = str(sc.get("procedure_name", "")).strip().lower()
    return (session_id or "global", q_norm, proc, domain or "default")

def _try_template_fast_path(query: str, evidence_candidates, field_types: list[str]) -> str | None:
    """Bước 3A Template Fast Path:
    Khi query chỉ hỏi đúng 1 field (fee, time, method, docs) và đã có field chunk tương ứng,
    kết xuất câu trả lời chuẩn trực tiếp, bỏ qua LLM sinh token để giảm độ trễ từ ~3s về <0.1s."""
    if not field_types or len(field_types) != 1 or not evidence_candidates:
        return None

    ftype = field_types[0]
    field_to_chunk_suffix = {
        "fee": "_fee",
        "time": "_time",
        "method": "_method",
        "docs": "_docs",
    }
    suffix = field_to_chunk_suffix.get(ftype)
    if not suffix:
        return None

    target_ev = next((ev for ev in evidence_candidates if ev.chunk_id and ev.chunk_id.endswith(suffix)), None)
    if not target_ev:
        return None

    content = (target_ev.content or "").strip()
    if not content:
        return None

    lines = [l.strip() for l in content.split("\n") if l.strip()]
    title = ""
    field_lines = []
    capture = False
    for line in lines:
        if line.startswith("Tên thủ tục:"):
            title = line.replace("Tên thủ tục:", "").strip()
        elif ":" in line and not capture:
            field_lines.append(line)
            capture = True
        elif capture:
            field_lines.append(line)

    if not field_lines:
        return None

    cid = target_ev.candidate_id
    info_body = "\n".join(field_lines)
    if title:
        return f"Về {title}, thông tin chi tiết như sau:\n\n{info_body} [{cid}]"
    return f"{info_body} [{cid}]"

def _is_useless_answer(answer: str) -> bool:
    """Kiểm tra câu trả lời rỗng, chỉ có citation, hoặc quá ngắn."""
    if not answer or not answer.strip():
        return True

    text = answer.strip()

    if (text.lower().strip() == FALLBACK_TEXT.lower().strip()):
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
    """Gọi async MCP từ pipeline sync.

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
    """Convert MCP evidence thành metadata tool_calls để backend/UI có thể trả về client."""
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
    on_token: Callable[[str], None] | None = None,
) -> AnswerResponse:
    """Run the complete AI Core / RAG pipeline."""
    # Normalize input
    if isinstance(query, (list, dict)):
        query = _extract_text(query)
    elif not isinstance(query, str):
        query = str(query) if query is not None else ""

    # Input guardrail
    t_start_pipeline = time.time()
    t_first_token = None

    def wrapped_on_token(tok: str):
        nonlocal t_first_token
        if t_first_token is None:
            t_first_token = time.time()
            print(f"[time] OVERALL TTFT = {t_first_token - t_start_pipeline:.2f}s")
        if on_token is not None:
            on_token(tok)

    t0_input = time.time()
    input_guard = validate_input(query)
    print(f"[time] input_guard = {time.time() - t0_input:.2f}s")

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
    # Bước 3B: Pipeline Answer Cache hit check
    cache_key = _get_cache_key(query, context, domain, session_id=session_id)
    if cache_key in _PIPELINE_ANSWER_CACHE:
        cached_resp = _PIPELINE_ANSWER_CACHE[cache_key]
        print(f"[pipeline] Cache hit for query='{query[:40]}' (proc='{cache_key[1]}')")
        if cached_resp.answer:
            wrapped_on_token(cached_resp.answer)
        return cached_resp

    # ---------------------------------------------------------
    # Layer 2 - Domain runtime + risk classifier
    runtime = get_domain_runtime(domain)
    domain = runtime.domain_id

    t0_risk = time.time()
    risk_result = classify_risk(query)
    print(f"[time] risk = {time.time() - t0_risk:.2f}s")

    effective_mode = resolve_mode(
        runtime.mode,
        risk_result,
    )

    # ---------------------------------------------------------
    # Out-of-scope location detection
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
    # Multi-intent branching
    if getattr(cfg, "MULTI_INTENT_ENABLED", False):
        from rag.multi.detector import detect_sub_queries
        sub_queries, truncated = detect_sub_queries(query, context, domain)
        if len(sub_queries) >= 2:
            from rag.multi.resolver import resolve_all
            from rag.multi.section import build_section_template

            sub_results = resolve_all(sub_queries, context, domain)

            sections = []
            answer_parts = []
            claims = []
            evidence_start_index = 1
            for res in sub_results:
                sec = build_section_template(res, evidence_start_index=evidence_start_index)
                sections.append(sec)
                evidence_start_index += len(res.chunks)
                if sec.status == "FOUND":
                    answer_parts.append(f"### {sec.title}\\n{sec.text}")
                else:
                    answer_parts.append(f"### {sec.title}\\n{sec.text}")
                claims.extend(sec.claims)

            final_answer = "\n\n".join(answer_parts)
            if truncated:
                final_answer += "\n\n(Lưu ý: Bạn đã hỏi quá nhiều thủ tục, hệ thống chỉ trả lời 8 thủ tục đầu tiên)."

            return AnswerResponse(
                answer=final_answer,
                claims=claims,
                needs_clarification=False,
                clarification_question=None,
                domain=domain,
                mode=effective_mode,
                sections=sections,
                truncated=truncated,
            )

    # ---------------------------------------------------------
    # Multi-agent preprocessing (Single-intent)
    t0_hist = time.time()
    history = history_reader(context)
    print(f"[time] history_reader = {time.time() - t0_hist:.2f}s")

    # ---------------------------------------------------------
    # Retrieve lightweight procedure/topic hints (và cache raw chunks).
    initial_chunks = []
    procedure_hint = procedure_reader(
        query=query,
        context=context,
        top_k=2,
        raw_results_out=initial_chunks,
    )

    # ---------------------------------------------------------
    # Synthesize the query using history + procedure hints (uses 1.5B model).
    t0_synth = time.time()
    consolidated = synthesizer(
        query=query,
        history=history,
        procedure_hint=procedure_hint,
        generator=synthesizer_generator,
        domain=domain,
    )
    print(f"[time] synthesizer = {time.time() - t0_synth:.2f}s")

    # ---------------------------------------------------------
    # Clarification branch
    if consolidated.needs_clarification:
        return AnswerResponse(
            answer=None,
            claims=[],
            needs_clarification=True,
            clarification_question=consolidated.clarification_question,
            domain=domain,
            mode=effective_mode,
            tool_calls=[],
        )

    # ---------------------------------------------------------
    # MCP tools
    tool_evidence = []
    try:
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
        print(
            "[pipeline] MCP tools unavailable: "
            f"{exc}"
        )
        tool_evidence = []

    tool_calls = _build_tool_calls(tool_evidence)

    # ---------------------------------------------------------
    # Two-step retrieval
    t0_retrieve = time.time()
    raw_to_use = initial_chunks if (consolidated.resolved_query.strip().lower() == query.strip().lower()) else None
    retrieved_chunks = retrieve_two_step(
        query=consolidated.resolved_query,
        context=context,
        domain=domain,
        raw_results=raw_to_use,
    )
    print(f"[time] retrieve_two_step = {time.time() - t0_retrieve:.2f}s")

    if (not retrieved_chunks and not tool_evidence):
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
        and top_score < runtime.min_retrieval_score
    ):
        print(
            "[pipeline] Strict mode: "
            f"Top-1 score {top_score:.3f} < {runtime.min_retrieval_score:.3f} -> NO EVIDENCE"
        )
        answer = runtime.no_evidence_message or FALLBACK_TEXT
        if runtime.disclaimer:
            answer = f"{answer}\n\n{runtime.disclaimer}"
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
    # Rerank
    ranked_chunks = (
        rerank(retrieved_chunks) if retrieved_chunks else []
    )

    # ---------------------------------------------------------
    # Build evidence
    evidence_candidates = build_evidence_candidates(ranked_chunks)
    evidence_candidates.extend(tool_evidence)

    if (not evidence_candidates and effective_mode == "strict"):
        answer = runtime.no_evidence_message or FALLBACK_TEXT
        if runtime.disclaimer:
            answer = f"{answer}\n\n{runtime.disclaimer}"
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
    # Prompt Builder
    t0_prompt = time.time()
    prompt = build_prompt(
        query=consolidated.resolved_query,
        evidence_candidates=evidence_candidates,
        context=context,
        domain=domain,
    )
    print(f"[time] prompt_build = {time.time() - t0_prompt:.2f}s")

    # ---------------------------------------------------------
    # Final Answer Generation
    from rag.generator import LLMUnavailableError

    try:
        generated_answer = generator(
            prompt
        )
    except LLMUnavailableError as exc:
        print(f"GENERATOR ERROR: {exc}")
        generated_answer = None

    # Apply output guard
    if generated_answer is not None:
        generated_answer = apply_output_guard(generated_answer)

    # Verification
    verification_result = verify_answer(
        answer=generated_answer,
        query=consolidated.resolved_query,
        evidence=evidence_candidates,
        domain=domain,
    )
    verification = map_verification_results(verification_result)

    # Build final response
    final_response = AnswerResponse(
        answer=generated_answer,
        claims=verification.claims,
        needs_clarification=verification.needs_clarification,
        clarification_question=verification.clarification_question,
        domain=domain,
        mode=effective_mode,
        tool_calls=tool_calls,
    )

    # Cache the response
    _PIPELINE_ANSWER_CACHE[cache_key] = final_response
    if len(_PIPELINE_ANSWER_CACHE) > _MAX_ANSWER_CACHE_SIZE:
        # simple LRU eviction
        oldest_key = next(iter(_PIPELINE_ANSWER_CACHE))
        del _PIPELINE_ANSWER_CACHE[oldest_key]

    total_pipeline = time.time() - t_start_pipeline
    print(f"[time] total_pipeline = {total_pipeline:.2f}s")

    return final_response


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

