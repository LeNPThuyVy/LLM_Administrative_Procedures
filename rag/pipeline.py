import asyncio
import re
import time
import unicodedata
from collections import OrderedDict
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

LOCATION_NOT_SUPPORTED_TEXT = (
    "Hiện tại hệ thống chỉ hỗ trợ tra cứu các thủ tục hành chính công áp dụng tại Thành phố Hồ Chí Minh."
)

# Danh sách tỉnh / thành phố lớn ngoài TP.HCM để phát hiện out-of-scope nhanh
# (tránh false positive bằng word boundary )
_NON_HCMC_PATTERNS = re.compile(
    r"\b(hà nội|hà nam|hải phòng|đà nẵng|hải dương|bắc ninh|quảng ninh|"
    r"thanh hóa|nghệ an|hà tĩnh|huế|thừa thiên huế|quảng bình|quảng trị|"
    r"quảng nam|quảng ngãi|bình định|phú yên|khánh hòa|nha trang|"
    r"ninh thuận|bình thuận|cần thơ|an giang|đồng tháp|tiền giang|"
    r"kiên giang|bến tre|vĩnh long|trà vinh|sóc trăng|bạc liêu|cà mau|"
    r"bình phước|tây ninh|bình dương|đồng nai|vũng tàu|bà rịa)\b",
    re.IGNORECASE | re.UNICODE,
)


def _extract_text(val: object) -> str:
    """Safely extract string text from string, list, or dict message content."""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return " ".join(_extract_text(item) for item in val if item)
    if isinstance(val, dict):
        if "text" in val and isinstance(val["text"], str):
            return val["text"]
        if "content" in val:
            return _extract_text(val["content"])
        return " ".join(_extract_text(v) for v in val.values() if v)
    return str(val) if val is not None else ""


def _fold_vietnamese_text(text: str) -> str:
    """Normalize Vietnamese text to lowercase ASCII for robust matching."""
    text = str(text or "").lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    return "".join(
        ch for ch in text
        if unicodedata.category(ch) != "Mn"
    )


def _is_underspecified_procedure_query(text: str) -> bool:
    """
    Detect generic requests that do not identify any actual procedure.
    Examples:
    - Tôi muốn làm thủ tục
    - Tôi cần làm thủ tục
    - Làm thủ tục
    """
    q = _fold_vietnamese_text(text)
    q = re.sub(r"[^a-z0-9\s]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()

    generic_patterns = {
        "lam thu tuc",
        "toi muon lam thu tuc",
        "toi can lam thu tuc",
        "toi muon hoi thu tuc",
        "toi can hoi thu tuc",
        "can lam thu tuc",
        "muon lam thu tuc",
    }

    return q in generic_patterns


def _detect_unsupported_location(text: str, domain: str | None = None) -> bool:
    """
    Return True if text contains a Vietnamese location that is
    explicitly NOT supported by the current domain.

    - Nếu domain không cấu hình supported_locations: trả False.
    - Nếu domain là administrative_procedures (hoặc rỗng): dùng _NON_HCMC_PATTERNS.
    - Với các domain khác: nếu câu hỏi chứa supported_locations của domain thì luôn cho phép;
      chỉ từ chối nếu có địa phương rõ ràng ngoài phạm vi.
    """
    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)

    if not runtime.supported_locations:
        return False

    text_lower = text.lower()
    # Nếu câu hỏi có nêu rõ việc thực hiện tại địa bàn được hỗ trợ (VD: hộ khẩu tỉnh khác nhưng làm tại TP.HCM)
    has_supported_loc = any(loc.lower() in text_lower for loc in runtime.supported_locations if loc)

    if domain == "administrative_procedures" or not domain:
        if has_supported_loc:
            return False
        return bool(_NON_HCMC_PATTERNS.search(text))

    if has_supported_loc:
        return False

    return bool(_NON_HCMC_PATTERNS.search(text))


def _answer_from_evidence(evidence_candidates, field_types: list[str] = None):
    """
    Nếu LLM không tạo được câu trả lời hữu ích,
    dùng trực tiếp evidence tốt nhất có chứa thông tin cần tìm.
    """
    if not evidence_candidates:
        return FALLBACK_TEXT

    # Nếu chỉ cần docs, tìm chunk có chứa "Thành phần hồ sơ:"
    if field_types and "docs" in field_types and len(field_types) == 1:
        for ev in evidence_candidates:
            content = (ev.content or "").strip()
            if "Thành phần hồ sơ:" in content:
                docs_part = content.split("Thành phần hồ sơ:")[1]
                return f"Thành phần hồ sơ:\n{docs_part.strip()} [{ev.candidate_id}]"

    # Nếu không filter được hoặc filter thất bại, trả về các chunk phù hợp (loại bỏ lặp Tên thủ tục)
    parts = []
    seen_titles = set()
    
    # 1. Ưu tiên chunk general: tìm các document_id có chunk _general
    general_docs = {
        ev.document_id for ev in evidence_candidates 
        if ev.chunk_id and ev.chunk_id.endswith("_general")
    }
    
    for ev in evidence_candidates:
        # Nếu doc này đã có general chunk, bỏ qua các chunk con (_docs, _fee...)
        if ev.document_id in general_docs and not (ev.chunk_id and ev.chunk_id.endswith("_general")):
            continue
            
        content = (ev.content or "").strip()
        if not content:
            continue
            
        # Tìm và xử lý dòng Tên thủ tục để tránh lặp
        title_match = re.search(r"^Tên thủ tục: (.*?)\n", content)
        if title_match:
            title = title_match.group(1).strip()
            if title not in seen_titles:
                parts.append(f"Tên thủ tục: {title}")
                seen_titles.add(title)
            # Cắt bỏ dòng Tên thủ tục ở chunk này
            content = content.replace(title_match.group(0), "").strip()
            
        if content:
            parts.append(f"{content} [{ev.candidate_id}]")
            
    if parts:
        return "\n\n".join(parts)

    return FALLBACK_TEXT


_PIPELINE_ANSWER_CACHE: OrderedDict[tuple, AnswerResponse] = OrderedDict()
_MAX_ANSWER_CACHE_SIZE = 500


def _get_cache_key(query: str, context: dict | None, domain: str | None, session_id: str | None = None) -> tuple:
    q_norm = (query or "").strip().lower()
    proc = ""
    if context:
        sc = context.get("structured_context") or {}
        if isinstance(sc, dict):
            proc = str(sc.get("procedure_name", "")).strip().lower()
    return (session_id or "global", q_norm, proc, domain or "default")


def _try_template_fast_path(query: str, evidence_candidates, field_types: list[str], domain: str | None = None) -> str | None:
    """
    Bước 3A Template Fast Path:
    Khi query chỉ hỏi đúng 1 field (fee, time, method, docs) và domain có chunk_field_specs tương ứng,
    kết xuất câu trả lời chuẩn trực tiếp, bỏ qua LLM sinh token để giảm độ trễ từ ~3s về <0.1s.
    """
    if not field_types or len(field_types) != 1 or not evidence_candidates:
        return None

    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)
    # Nếu domain không cấu hình chunk_field_specs (hoặc chỉ có general), tắt fast path
    if not runtime.config.chunk_field_specs or list(runtime.config.chunk_field_specs.keys()) == ["general"]:
        return None

    ftype = field_types[0]
    specs = runtime.config.chunk_field_specs

    # Map ftype -> spec key trong config
    ftype_map = {
        "fee": "fee",
        "time": "processing_time",
        "method": "submission_method",
        "docs": "required_documents",
    }
    spec_key = ftype_map.get(ftype)
    if not spec_key or spec_key not in specs:
        return None

    target_suffix = specs[spec_key].get("suffix")
    target_label = specs[spec_key].get("label", "")

    # Tìm chunk có suffix tương ứng
    for ev in evidence_candidates:
        if ev.chunk_id and ev.chunk_id.endswith(target_suffix):
            content = (ev.content or "").strip()
            if not content:
                continue
            # Chuẩn hóa title
            title = ev.title or ""
            if not title:
                m = re.search(r"^Tên thủ tục: (.*?)\n", content)
                if m:
                    title = m.group(1).strip()
            # Bỏ prefix nếu có
            body = content
            prefix_pattern = rf"^(?:Tên thủ tục: [^\n]+\n+)?(?:{re.escape(target_label)}:\s*)"
            body = re.sub(prefix_pattern, "", body, flags=re.IGNORECASE).strip()
            if not body:
                continue
            # Render template có citation
            rendered = f"{title}\n\n**{target_label}:**\n{body} [{ev.candidate_id}]"
            return rendered

    return None


def _is_useless_answer(answer: str) -> bool:
    """
    Kiểm tra câu trả lời rỗng, chỉ có citation, hoặc dưới 15 ký tự.

    GĐ1 fix: Chỉ coi là vô dụng khi:
    - Rỗng / chỉ whitespace
    - Chỉ chứa citation [EC_xxx]
    - Dưới 15 ký tự sau khi bỏ citation

    KHÔNG còn đánh dấu "chưa đủ để trả lời" là vô dụng —
    câu trả lời đúng có kèm một ý thiếu thông tin vẫn được giữ.
    _answer_from_evidence chỉ dùng khi generator lỗi hoặc trả rỗng.
    """

    if not answer or not answer.strip():
        return True

    text = answer.strip()

    # Chỉ từ chối khi đây là TOÀN BỘ nội dung là FALLBACK_TEXT (không có thêm gì)
    if text.lower().strip() == FALLBACK_TEXT.lower().strip():
        return True

    # Ví dụ: [EC_001]
    citation_only = re.fullmatch(
        r"\s*\[?EC_\d{3}\]?\s*[.!]?\s*",
        text,
    )

    if citation_only:
        return True

    # Quá ngắn thì cũng coi là không hữu ích
    cleaned = re.sub(
        r"\[?EC_\d{3}\]?",
        "",
        text,
    ).strip()

    # GĐ1 fix: 15 ký tự thay vì 25 để không lọc nhầm câu trả lời ngắn hợp lệ
    # (VD: "Phí: 50.000 VNĐ.")
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
    """
    Run the complete AI Core / RAG pipeline.
    """
    # session_id is used for cache key partitioning

    if isinstance(query, (list, dict)):
        query = _extract_text(query)
    elif not isinstance(query, str):
        query = str(query) if query is not None else ""

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
            f"[guardrail] Blocked input: "
            f"{input_guard.reason} | "
            f"{mask_sensitive_for_log(query)}"
        )

        return AnswerResponse(
            answer="Yêu cầu này không thể được xử lý vì vi phạm quy tắc an toàn.",
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

    # Bước 3B: Pipeline Answer Cache hit check
    cache_key = _get_cache_key(query, context, domain, session_id=session_id)
    if cache_key in _PIPELINE_ANSWER_CACHE:
        _PIPELINE_ANSWER_CACHE.move_to_end(cache_key)
        cached_resp = _PIPELINE_ANSWER_CACHE[cache_key]
        print(f"[pipeline] Cache hit for query='{query[:40]}' (proc='{cache_key[1]}')")
        if cached_resp.answer:
            wrapped_on_token(cached_resp.answer)
        return cached_resp

    # Layer 2 - Domain runtime + risk classifier
    runtime = get_domain_runtime(domain)
    domain = runtime.domain_id

    t0_risk = time.time()
    domain_risk_kw = getattr(runtime.config, "risk_keywords", None) if hasattr(runtime, "config") else None
    risk_result = classify_risk(query, domain_risk_keywords=domain_risk_kw)
    effective_mode = resolve_mode(
        runtime.mode,
        risk_result,
    )
    print(f"[time] risk = {time.time() - t0_risk:.2f}s (mode: {runtime.mode} -> {effective_mode})")

    # ---------------------------------------------------------
    # Generic / underspecified procedure clarification
    # ---------------------------------------------------------
    if _is_underspecified_procedure_query(query):
        clarification = (
            "Bạn muốn thực hiện thủ tục nào? "
            "Vui lòng cho biết tên thủ tục cụ thể "
            "để tôi hỗ trợ."
        )

        print(
            "[pipeline] Generic procedure query "
            f"requires clarification: {query[:100]!r}"
        )

        return AnswerResponse(
            answer=clarification,
            claims=[],
            needs_clarification=True,
            clarification_question=clarification,
            domain=domain,
            mode=effective_mode,
            tool_calls=[],
        )

    # ---------------------------------------------------------
    # GĐ1 fix — Out-of-scope location detection (mục 5)
    # Chỉ kiểm tra tin nhắn user HIỆN TẠI, không quét history.
    # Trước đây quét cả history khiến user nhắc "Hà Nội" một lần
    # là mọi lượt sau đều bị từ chối.
    # ---------------------------------------------------------
    if _detect_unsupported_location(query, domain=domain):
        print(
            f"[pipeline] Unsupported location in current query: "
            f"{query[:100]!r}"
        )
        reject_message = (
            runtime.config.out_of_scope_message
            if hasattr(runtime, "config") and runtime.config.out_of_scope_message
            else LOCATION_NOT_SUPPORTED_TEXT
        )
        return AnswerResponse(
            answer=reject_message,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
            tool_calls=[],
        )

    # ---------------------------------------------------------
    # Multi-intent branching
    # ---------------------------------------------------------
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
                    answer_parts.append(f"### {sec.title}\n{sec.text}")
                else:
                    answer_parts.append(f"### {sec.title}\n{sec.text}")
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
                tool_calls=[],
            )

    # ---------------------------------------------------------
    # Multi-agent preprocessing (Single-intent)
    # ---------------------------------------------------------
    t0_hist = time.time()
    history = history_reader(context)
    print(f"[time] history_reader = {time.time() - t0_hist:.2f}s")

    # Retrieve lightweight procedure/topic hints (và cache raw chunks).
    initial_chunks = []
    procedure_hint = procedure_reader(
        query=query,
        context=context,
        top_k=2,
        raw_results_out=initial_chunks,
        domain=domain,
    )

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

    # Clarification branch
    if consolidated.needs_clarification:
        clarification_text = (
            consolidated.clarification_question
            or runtime.clarification_prompt
            or "Bạn muốn hỏi về nội dung cụ thể nào? Vui lòng nêu rõ thông tin để tôi có thể hỗ trợ chính xác hơn."
        )
        return AnswerResponse(
            answer=clarification_text,
            claims=[],
            needs_clarification=True,
            clarification_question=clarification_text,
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

    if not retrieved_chunks and not tool_evidence:
        clarification_text = (
            runtime.clarification_prompt
            or "Bạn muốn hỏi về nội dung cụ thể nào? Vui lòng nêu rõ thông tin để tôi có thể hỗ trợ chính xác hơn."
        )
        return AnswerResponse(
            answer=clarification_text,
            claims=[],
            needs_clarification=True,
            clarification_question=clarification_text,
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
        and not tool_evidence
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

    # 2. Rerank
    ranked_chunks = (
        rerank(retrieved_chunks, query=consolidated.resolved_query)
        if retrieved_chunks
        else []
    )

    # 3. Build evidence
    evidence_candidates = build_evidence_candidates(ranked_chunks)
    evidence_candidates.extend(tool_evidence)

    if not evidence_candidates and effective_mode == "strict":
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

    # 4. Prompt Builder
    from rag.prompt_builder import _detect_field_types
    detected_fields = _detect_field_types(consolidated.resolved_query)

    t0_prompt = time.time()
    prompt = build_prompt(
        query=consolidated.resolved_query,
        evidence_candidates=evidence_candidates,
        context=context,
        domain=domain,
    )
    print(f"[time] prompt_build = {time.time() - t0_prompt:.2f}s")

    # 5. Fast Path & Generation
    fast_answer = None
    if generator is generate_answer_3b:
        fast_answer = _try_template_fast_path(
            consolidated.resolved_query,
            evidence_candidates,
            detected_fields,
            domain=domain,
        )
    if fast_answer:
        print(f"[pipeline] Fast Path: rendered answer directly from field evidence ({detected_fields}).")
        generated_answer = fast_answer
        wrapped_on_token(fast_answer)
    else:
        from rag.generator import LLMUnavailableError, stream_answer_3b
        t0_gen = time.time()
        try:
            if on_token is not None:
                token_list = []
                for tok in stream_answer_3b(prompt):
                    token_list.append(tok)
                    wrapped_on_token(tok)
                generated_answer = "".join(token_list)
            else:
                generated_answer = generator(prompt)
        except LLMUnavailableError as exc:
            print(f"GENERATOR ERROR: {exc}")
            return AnswerResponse(
                answer="Hệ thống đang bận, vui lòng thử lại sau ít phút.",
                claims=[],
                needs_clarification=False,
                clarification_question=None,
                domain=domain,
                mode=effective_mode,
                tool_calls=tool_calls,
            )
        except Exception as exc:
            print("GENERATOR ERROR:", repr(exc))
            generated_answer = ""
        print(f"[time] generate = {time.time() - t0_gen:.2f}s")

    # 6. Fallback if useless answer
    if _is_useless_answer(generated_answer):
        from rag.prompt_builder import _detect_field_types
        field_types = _detect_field_types(consolidated.resolved_query)
        generated_answer = _answer_from_evidence(evidence_candidates, field_types)

    # 7. Verification & 8. Mapper (chỉ chạy khi effective_mode == "strict")
    if effective_mode == "strict":
        t0_ver = time.time()
        verification_results = verify_answer(
            generated_answer=generated_answer,
            evidence_candidates=evidence_candidates,
        )
        print(f"[time] verify = {time.time() - t0_ver:.2f}s")

        verified_claims = map_verification_results(
            verification_results=verification_results,
            evidence_candidates=evidence_candidates,
        )
        # Strict: answer phải có claim đã được evidence support.
        if not verified_claims:
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
    else:
        # Friendly: bỏ qua bước verification & mapper để tối ưu tốc độ, không ép citation
        verified_claims = []

    # Output guard
    t0_out = time.time()
    generated_answer = apply_output_guard(
        generated_answer,
        effective_mode,
        runtime.disclaimer,
        allowed_text=" ".join(ev.content or "" for ev in evidence_candidates),
    )
    print(f"[time] output_guard = {time.time() - t0_out:.2f}s")

    final_response = AnswerResponse(
        answer=generated_answer,
        claims=verified_claims,
        needs_clarification=False,
        clarification_question=None,
        domain=domain,
        mode=effective_mode,
        tool_calls=tool_calls,
    )

    if len(_PIPELINE_ANSWER_CACHE) >= _MAX_ANSWER_CACHE_SIZE:
        _PIPELINE_ANSWER_CACHE.popitem(last=False)
    _PIPELINE_ANSWER_CACHE[cache_key] = final_response

    print(f"[time] total_pipeline = {time.time() - t_start_pipeline:.2f}s")
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
        normalized_query = _extract_text(query)
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
        """
        Adapter để answer_query() vẫn nhận generator
        Callable[[str], str], nhưng token được đẩy ra
        queue ngay khi model sinh.
        """
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

    # Trường hợp pipeline kết thúc trước generation,
    # ví dụ clarification/no-evidence/input guard.
    if not state["streamed"] and result.answer:
        yield {
            "type": "token",
            "text": result.answer,
        }

    yield {
        "type": "final",
        "response": result,
    }
