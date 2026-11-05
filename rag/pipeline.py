from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace

import my_config as cfg
from domains.runtime import get_domain_runtime
from guardrails.output import apply_output_guard
from guardrails.risk import classify_risk, resolve_mode
from rag.evidence_builder import build_evidence_candidates
from rag.generator import (
    LLMUnavailableError,
    generate_answer_1_5b,
    generate_answer_3b,
    stream_answer_3b,
)
from rag.history_reader import history_reader
from rag.mapper import AnswerResponse, map_verification_results
from rag.pipeline_cache import (
    get_cache_key,
    get_cached_answer,
    set_cached_answer,
)
from rag.pipeline_fast_path import (
    answer_from_evidence,
    is_useless_answer,
    try_template_fast_path,
)
from rag.pipeline_guards import (
    FALLBACK_TEXT,
    LOCATION_NOT_SUPPORTED_TEXT,
    check_early_guards,
    detect_unsupported_location,
    extract_text,
    fold_vietnamese_text,
    is_underspecified_procedure_query,
)
from rag.pipeline_tools import build_tool_calls, run_tools_sync
from rag.procedure_reader import procedure_reader
from rag.prompt_builder import _detect_field_types, build_prompt
from rag.rerank import rerank
from rag.retrieval import retrieve_two_step
from rag.streaming import answer_question_stream
from rag.synthesizer import synthesizer
from rag.verification import verify_answer

logger = logging.getLogger(__name__)

# Backwards compatibility aliases
_extract_text = extract_text
_fold_vietnamese_text = fold_vietnamese_text
_is_underspecified_procedure_query = is_underspecified_procedure_query
_detect_unsupported_location = detect_unsupported_location
_answer_from_evidence = answer_from_evidence
_try_template_fast_path = try_template_fast_path
_is_useless_answer = is_useless_answer
_get_cache_key = get_cache_key
_run_tools_sync = run_tools_sync
_build_tool_calls = build_tool_calls


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
        query = extract_text(query)
    elif not isinstance(query, str):
        query = str(query) if query is not None else ""

    t_start_pipeline = time.time()
    t_first_token = None

    def wrapped_on_token(tok: str):
        nonlocal t_first_token
        if t_first_token is None:
            t_first_token = time.time()
            logger.info("[time] OVERALL TTFT = %.2fs", t_first_token - t_start_pipeline)
            print(f"[time] OVERALL TTFT = {t_first_token - t_start_pipeline:.2f}s")
        if on_token is not None:
            on_token(tok)

    if context is None:
        context = {}

    # Bước 3B: Pipeline Answer Cache hit check
    cache_key = get_cache_key(query, context, domain, session_id=session_id)
    cached_resp = get_cached_answer(cache_key)
    if cached_resp is not None:
        logger.info("[pipeline] Cache hit for query='%s' (proc='%s')", query[:40], cache_key[1])
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
    effective_mode = resolve_mode(runtime.mode, risk_result)
    logger.info("[time] risk = %.2fs (mode: %s -> %s)", time.time() - t0_risk, runtime.mode, effective_mode)
    print(f"[time] risk = {time.time() - t0_risk:.2f}s (mode: {runtime.mode} -> {effective_mode})")

    # Early guards check: input validation, empty query, medical emergency, underspecified query, out of scope
    early_response = check_early_guards(
        query=query,
        domain=domain,
        effective_mode=effective_mode,
        runtime=runtime,
        risk_result=risk_result,
    )
    if early_response is not None:
        return early_response

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

    # Multi-agent preprocessing (Single-intent)
    t0_hist = time.time()
    history = history_reader(context)
    print(f"[time] history_reader = {time.time() - t0_hist:.2f}s")

    initial_chunks = []
    procedure_hint = procedure_reader(
        query=query,
        context=context,
        top_k=2,
        raw_results_out=initial_chunks,
        domain=domain,
    )

    t0_synth = time.time()
    consolidated = synthesizer(
        query=query,
        history=history,
        procedure_hint=procedure_hint,
        generator=synthesizer_generator,
        domain=domain,
    )
    print(f"[time] synthesizer = {time.time() - t0_synth:.2f}s")

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

    # MCP tools
    tool_evidence = []
    try:
        tool_runtime = replace(runtime, mode=effective_mode)
        tool_evidence = run_tools_sync(
            query=consolidated.resolved_query,
            runtime=tool_runtime,
            context=context,
        )
    except Exception as exc:
        logger.warning("[pipeline] MCP tools unavailable: %s", exc)
        tool_evidence = []

    tool_calls = build_tool_calls(tool_evidence)

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
        logger.info(
            "[pipeline] Strict mode: Top-1 score %.3f < %.3f -> NO EVIDENCE",
            top_score,
            runtime.min_retrieval_score,
        )
        print(
            f"[pipeline] Strict mode: Top-1 score {top_score:.3f} < {runtime.min_retrieval_score:.3f} -> NO EVIDENCE"
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

    # Rerank
    ranked_chunks = (
        rerank(retrieved_chunks, query=consolidated.resolved_query)
        if retrieved_chunks
        else []
    )

    # Build evidence
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

    # Prompt Builder
    detected_fields = _detect_field_types(consolidated.resolved_query)
    t0_prompt = time.time()
    prompt = build_prompt(
        query=consolidated.resolved_query,
        evidence_candidates=evidence_candidates,
        context=context,
        domain=domain,
    )
    print(f"[time] prompt_build = {time.time() - t0_prompt:.2f}s")

    # Fast Path & Generation
    fast_answer = None
    if generator is generate_answer_3b:
        fast_answer = try_template_fast_path(
            consolidated.resolved_query,
            evidence_candidates,
            detected_fields,
            domain=domain,
        )
    if fast_answer:
        logger.info("[pipeline] Fast Path: rendered answer directly from field evidence (%s).", detected_fields)
        print(f"[pipeline] Fast Path: rendered answer directly from field evidence ({detected_fields}).")
        generated_answer = fast_answer
        wrapped_on_token(fast_answer)
    else:
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
            logger.error("GENERATOR ERROR: %s", exc)
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
            logger.exception("GENERATOR ERROR: %r", exc)
            print("GENERATOR ERROR:", repr(exc))
            generated_answer = ""
        print(f"[time] generate = {time.time() - t0_gen:.2f}s")

    # Fallback if useless answer
    if is_useless_answer(generated_answer):
        field_types = _detect_field_types(consolidated.resolved_query)
        generated_answer = answer_from_evidence(evidence_candidates, field_types)

    # Verification & Mapper (chỉ chạy khi effective_mode == "strict")
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

    set_cached_answer(cache_key, final_response)
    print(f"[time] total_pipeline = {time.time() - t_start_pipeline:.2f}s")
    return final_response
