import re
import time
from collections.abc import Callable

import my_config as cfg
from rag.evidence_builder import build_evidence_candidates
from queue import Queue
from threading import Thread
from rag.generator import generate_answer_1_5b, generate_answer_3b, stream_answer_3b
from rag.history_reader import history_reader
from rag.mapper import AnswerResponse, map_verification_results
from rag.procedure_reader import procedure_reader
from rag.prompt_builder import build_prompt
from rag.rerank import rerank
from rag.retrieval import retrieve, retrieve_two_step
from rag.synthesizer import synthesizer
from rag.verification import filter_answer_by_verification, verify_answer
from domains.runtime import get_domain_runtime
from guardrails.risk import classify_risk, resolve_mode
from guardrails.input import validate_input, mask_sensitive_for_log
from guardrails.output import apply_output_guard
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
        return " ".join(_extract_text(item) for item in val if item)
    if isinstance(val, dict):
        if "text" in val and isinstance(val["text"], str):
            return val["text"]
        if "content" in val:
            return _extract_text(val["content"])
        return " ".join(_extract_text(v) for v in val.values() if v)
    return str(val) if val is not None else ""


def _detect_unsupported_location(text: str, domain: str | None = None) -> bool:
    """
    Return True if text contains a Vietnamese location that is
    explicitly NOT supported by the current domain.
    """
    from domains.runtime import get_domain_runtime
    from rag.text_normalizer import fold_accents
    runtime = get_domain_runtime(domain)

    if not runtime.supported_locations:
        return False

    text_lower = text.lower()
    text_folded = fold_accents(text_lower)
    has_supported_loc = any(
        loc.lower() in text_lower or fold_accents(loc.lower()) in text_folded
        for loc in runtime.supported_locations if loc
    )

    if has_supported_loc:
        return False

    if _NON_HCMC_PATTERNS.search(text):
        return True

    non_hcm_folded = re.compile(
        r"\b(binh duong|binh phuoc|dong nai|long an|tay ninh|"
        r"ba ria|vung tau|tien giang|can tho|ha noi|da nang|"
        r"hai phong|nha trang|da lat|quy nhon|"
        r"hai duong|nam dinh|ninh binh)\b",
        re.IGNORECASE,
    )
    return bool(non_hcm_folded.search(text_folded))


def _is_out_of_scope_query(
    query: str,
    domain: str | None = None,
    top_doc_title: str = "",
    top_vector_score: float = 0.0,
    generator: Callable[[str], str] | None = None,
) -> bool:
    """
    Return True if the query is out-of-scope for the current strict domain.
    """
    runtime = get_domain_runtime(domain)
    if runtime.mode != "strict" and domain not in (None, "administrative_procedures"):
        return False

    from rag.scope_classifier import classify_query_scope
    in_scope, _reason = classify_query_scope(
        query=query,
        top_doc_title=top_doc_title,
        top_vector_score=top_vector_score,
        domain=domain,
        generator=generator,
    )
    return not in_scope


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


from collections import OrderedDict
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
    Khi query hỏi 1 hoặc 2 field cụ thể (fee, time, method, docs) và domain có chunk_field_specs tương ứng,
    kết xuất câu trả lời chuẩn trực tiếp từ bằng chứng, bỏ qua LLM sinh token để giảm độ trễ và tránh bịa đặt.
    """
    if not field_types or len(field_types) > 2 or not evidence_candidates:
        return None

    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)
    if not runtime.config.chunk_field_specs or list(runtime.config.chunk_field_specs.keys()) == ["general"]:
        return None

    field_to_chunk_suffix = {
        "fee": "_fee",
        "time": "_time",
        "method": "_method",
        "docs": "_docs",
    }

    primary_doc_id = evidence_candidates[0].document_id
    title = ""
    rendered_sections = []

    for ftype in field_types:
        suffix = field_to_chunk_suffix.get(ftype)
        if not suffix:
            continue
        target_ev = next(
            (
                ev for ev in evidence_candidates
                if ev.document_id == primary_doc_id and ev.chunk_id and ev.chunk_id.endswith(suffix)
            ),
            None,
        )
        if not target_ev:
            target_ev = next((ev for ev in evidence_candidates if ev.chunk_id and ev.chunk_id.endswith(suffix)), None)
        if not target_ev:
            return None

        content = (target_ev.content or "").strip()
        if not content:
            return None

        lines = [l.strip() for l in content.split("\n") if l.strip()]
        field_lines = []
        capture = False
        for line in lines:
            if line.startswith("Tên thủ tục:"):
                if not title:
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
        rendered_sections.append(f"{info_body} [{cid}]")

    if not rendered_sections:
        return None

    joined_body = "\n\n".join(rendered_sections)
    if title:
        return f"Về {title}, thông tin chi tiết như sau:\n\n{joined_body}"
    return joined_body


def _is_useless_answer(answer: str) -> bool:
    """
    Kiểm tra câu trả lời rỗng, chỉ có citation, hoặc dưới 15 ký tự.
    """

    if not answer or not answer.strip():
        return True

    text = answer.strip()

    if text.lower().strip() == FALLBACK_TEXT.lower().strip():
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
            "[guardrail] Blocked input: "
            f"{input_guard.reason} | "
            f"{mask_sensitive_for_log(query)}"
        )

        return AnswerResponse(
            answer="Yêu cầu này không thể được xử lý vì vi phạm quy tắc an toàn.",
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode="strict",
        )
    if not query or not query.strip():
        return AnswerResponse(
            answer="",
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
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

    # Nhóm 2: Early safety reject for medical emergencies & poisoning in non-medical domain
    if any(r == "medical" or "ngộ độc" in r or "cấp cứu" in r for r in risk_result.reasons):
        q_low = query.lower()
        if any(w in q_low for w in ["uống thuốc", "thuốc gì", "khó thở", "ngộ độc", "cấp cứu", "sơ cứu", "chữa trị", "bệnh viện"]):
            return AnswerResponse(
                answer=(
                    "Hệ thống không thể tư vấn về y tế, dùng thuốc hoặc sơ cứu điều trị tại nhà. "
                    "Trong trường hợp khẩn cấp hoặc có dấu hiệu ngộ độc, khó thở, vui lòng liên hệ ngay cơ sở y tế gần nhất "
                    "hoặc gọi cấp cứu 115 để được hỗ trợ chuyên môn kịp thời."
                ),
                claims=[],
                needs_clarification=False,
                clarification_question=None,
                domain=domain,
                mode=effective_mode,
            )

    # ---------------------------------------------------------
    # GĐ1 fix — Out-of-scope location detection (mục 5)
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
                truncated=truncated
            )

    # ---------------------------------------------------------
    # Multi-agent preprocessing (Single-intent)
    # ---------------------------------------------------------
    t0_hist = time.time()
    history = history_reader(context)

    # 2. Retrieve lightweight procedure/topic hints (và cache raw chunks).
    initial_chunks = []
    procedure_hint = procedure_reader(
        query=query,
        context=context,
        top_k=2,
        raw_results_out=initial_chunks,
        domain=domain,
    )
    print(f"[time] history/procedure_reader = {time.time() - t0_hist:.2f}s")

    # 3. Synthesize the query using history + procedure hints (uses 1.5B model).
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
    # ---------------------------------------------------------
    if consolidated.needs_clarification:
        clarification_text = (
            consolidated.clarification_question
            or runtime.clarification_prompt
            or "Bạn muốn hỏi về nội dung nào? Vui lòng cung cấp thêm thông tin cụ thể để tôi có thể hỗ trợ bạn."
        )
        return AnswerResponse(
            answer=clarification_text,
            claims=[],
            needs_clarification=True,
            clarification_question=clarification_text,
            domain=domain,
            mode=effective_mode,
        )

    # ---------------------------------------------------------
    # Official RAG pipeline
    # ---------------------------------------------------------

    # 1. GĐ2: Two-step retrieval để tránh nhầm thủ tục
    t0_retrieve = time.time()
    raw_to_use = initial_chunks if (consolidated.resolved_query.strip().lower() == query.strip().lower()) else None
    retrieved_chunks = retrieve_two_step(
        query=consolidated.resolved_query,
        context=context,
        domain=domain,
        raw_results=raw_to_use,
    )
    print(f"[time] retrieve_two_step = {time.time() - t0_retrieve:.2f}s")

    if not retrieved_chunks:
        out_msg = (
            "Thủ tục hoặc thông tin bạn hỏi hiện không thuộc "
            "thẩm quyền giải quyết của bộ phận một cửa cấp xã/phường hoặc chưa có trong cơ sở dữ liệu."
        )
        if runtime.disclaimer:
            out_msg = f"{out_msg}\n\n{runtime.disclaimer}"
        return AnswerResponse(
            answer=out_msg,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
        )

    # Nhóm 3: Chống bịa đặt đối với các thủ tục không thuộc phạm vi cơ sở dữ liệu
    top_chunk_meta = retrieved_chunks[0].metadata or {}
    top_doc_title = str(top_chunk_meta.get("title", "") or "")
    top_vec_score = float(top_chunk_meta.get("_vector_score", 0.0))

    if _is_out_of_scope_query(
        query=consolidated.resolved_query,
        domain=domain,
        top_doc_title=top_doc_title,
        top_vector_score=top_vec_score,
        generator=synthesizer_generator,
    ):
        print(f"[pipeline] Out of scope topic detected in query: {query[:60]}")
        out_msg = (
            "Thủ tục hoặc thông tin bạn hỏi (hộ chiếu, visa, giấy phép lái xe, thuế, v.v.) hiện không thuộc "
            "thẩm quyền giải quyết của bộ phận một cửa cấp xã/phường hoặc không có trong cơ sở dữ liệu."
        )
        if runtime.disclaimer:
            out_msg = f"{out_msg}\n\n{runtime.disclaimer}"
        return AnswerResponse(
            answer=out_msg,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
        )

    # Issue #1 — Relevance threshold gate.
    top_score = retrieved_chunks[0].retrieval_score

    if (
        effective_mode == "strict"
        and top_score < runtime.min_retrieval_score
    ):
        print(
            f"[pipeline] Strict mode: Top-1 score "
            f"{top_score:.3f} < "
            f"{runtime.min_retrieval_score:.3f} -> NO EVIDENCE"
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
        )

    # 2. Rerank
    ranked_chunks = rerank(retrieved_chunks, query=consolidated.resolved_query)

    # 3. Build evidence
    evidence_candidates = build_evidence_candidates(ranked_chunks)

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
        )

    # 4. Prompt Builder
    t0_prompt = time.time()
    prompt = build_prompt(
        query=consolidated.resolved_query,
        evidence_candidates=evidence_candidates,
        context=context,
        domain=domain,
    )
    print(f"[time] prompt_build = {time.time() - t0_prompt:.2f}s")

    # 5. Final Answer Generation (Strict buffers tokens until verification completes)
    from rag.prompt_builder import _detect_field_types
    detected_fields = _detect_field_types(consolidated.resolved_query, context=context, domain=domain)

    fast_answer = None
    if generator is generate_answer_3b:
        fast_answer = _try_template_fast_path(consolidated.resolved_query, evidence_candidates, detected_fields, domain=domain)
    if fast_answer:
        print(f"[pipeline] Fast Path: rendered answer directly from field evidence ({detected_fields}).")
        generated_answer = fast_answer
    else:
        from rag.generator import LLMUnavailableError, stream_answer_3b
        t0_gen = time.time()
        try:
            if on_token is not None and effective_mode != "strict":
                token_list = []
                for tok in stream_answer_3b(prompt):
                    token_list.append(tok)
                    wrapped_on_token(tok)
                generated_answer = "".join(token_list)
            elif on_token is not None and effective_mode == "strict":
                # Strict mode: buffer tokens first, verify, then emit
                token_list = list(stream_answer_3b(prompt))
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
            )
        except Exception as exc:
            print("GENERATOR ERROR:", repr(exc))
            generated_answer = ""
        print(f"[time] generate = {time.time() - t0_gen:.2f}s")

    # 6. Fallback if useless answer
    if _is_useless_answer(generated_answer):
        generated_answer = _answer_from_evidence(evidence_candidates, detected_fields)

    # 7. Verification & 8. Mapper (chỉ chạy khi effective_mode == "strict")
    if effective_mode == "strict":
        t0_ver = time.time()
        verification_results = verify_answer(
            generated_answer=generated_answer,
            evidence_candidates=evidence_candidates,
        )
        filtered_answer, kept_results, has_critical_conflict = filter_answer_by_verification(
            generated_answer=generated_answer,
            verification_results=verification_results,
        )
        print(f"[time] verify = {time.time() - t0_ver:.2f}s")

        # If critical conflict (number/negation hallucination) or no supported claims remain,
        # attempt direct evidence extraction before falling back to no_evidence_message.
        if has_critical_conflict or not kept_results:
            evidence_fallback = _answer_from_evidence(evidence_candidates, detected_fields)
            if not _is_useless_answer(evidence_fallback):
                fb_ver = verify_answer(evidence_fallback, evidence_candidates)
                fb_filtered, fb_kept, fb_conflict = filter_answer_by_verification(evidence_fallback, fb_ver)
                if fb_kept and not fb_conflict:
                    filtered_answer = fb_filtered
                    kept_results = fb_kept
                    has_critical_conflict = False

        if has_critical_conflict or not kept_results:
            answer = runtime.no_evidence_message or FALLBACK_TEXT
            if runtime.disclaimer:
                answer = f"{answer}\n\n{runtime.disclaimer}"
            if on_token is not None:
                wrapped_on_token(answer)
            return AnswerResponse(
                answer=answer,
                claims=[],
                needs_clarification=False,
                clarification_question=None,
                domain=domain,
                mode=effective_mode,
            )

        generated_answer = filtered_answer
        verified_claims = map_verification_results(
            verification_results=kept_results,
            evidence_candidates=evidence_candidates,
        )
    else:
        # Friendly: bỏ qua bước verification & mapper để tối ưu tốc độ, không ép citation
        verified_claims = []
        
    t0_out = time.time()
    generated_answer = apply_output_guard(
        generated_answer,
        effective_mode,
        runtime.disclaimer,
        allowed_text=" ".join(ev.content or "" for ev in evidence_candidates),
    )
    print(f"[time] output_guard = {time.time() - t0_out:.2f}s")

    # Emit buffered answer in strict mode (or fast path) after verification & output guard
    if on_token is not None and (effective_mode == "strict" or fast_answer is not None):
        wrapped_on_token(generated_answer)
    
    final_response = AnswerResponse(
        answer=generated_answer,
        claims=verified_claims,
        needs_clarification=False,
        clarification_question=None,
        domain=domain,
        mode=effective_mode,
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
    Streaming entry point adapter.
    Chạy answer_query và yield các sự kiện:
      - {"type": "token", "text": "..."}
      - {"type": "final", "response": AnswerResponse}
    Đảm bảo 100% tuân thủ buffer-then-stream và verification của Bug 4.
    """
    token_queue = Queue()
    state = {
        "result": None,
        "error": None,
        "token_emitted": False,
    }

    def on_token(tok: str):
        if tok:
            state["token_emitted"] = True
            token_queue.put(("token", tok))

    custom_generator = generate_answer_3b
    if stream_generator is not None and stream_generator is not stream_answer_3b:
        def custom_generator(prompt: str, **kwargs) -> str:
            chunks = []
            for tok in stream_generator(prompt):
                if tok:
                    chunks.append(tok)
            return "".join(chunks)

    def worker():
        try:
            state["result"] = answer_query(
                query=query,
                session_id=session_id,
                context=context,
                domain=domain,
                generator=custom_generator,
                synthesizer_generator=synthesizer_generator,
                on_token=on_token,
            )
        except Exception as exc:
            state["error"] = exc
        finally:
            token_queue.put(("done", None))

    thread = Thread(target=worker, daemon=True)
    thread.start()

    while True:
        event_type, payload = token_queue.get()
        if event_type == "token":
            yield {"type": "token", "text": payload}
        elif event_type == "done":
            break

    thread.join()

    if state["error"] is not None:
        raise state["error"]

    result = state["result"]
    if result is None:
        from domains.runtime import get_domain_runtime
        from guardrails.risk import classify_risk, resolve_mode
        runtime = get_domain_runtime(domain)
        risk_result = classify_risk(query, domain_risk_keywords=getattr(runtime.config, "risk_keywords", None) if hasattr(runtime, "config") else None)
        effective_mode = resolve_mode(runtime.mode, risk_result)
        result = AnswerResponse(
            answer="",
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
        )

    if not state["token_emitted"] and result.answer:
        yield {"type": "token", "text": result.answer}

    yield {"type": "final", "response": result}
