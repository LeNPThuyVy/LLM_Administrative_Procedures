import re
from collections.abc import Callable

import my_config as cfg
from rag.evidence_builder import build_evidence_candidates
from rag.hybrid_generator import generate_hybrid
from rag.history_reader import history_reader
from rag.mapper import AnswerResponse, map_verification_results
from rag.procedure_reader import procedure_reader
from rag.prompt_builder import build_prompt
from rag.rerank import rerank
from rag.retrieval import retrieve
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
        return " ".join(_extract_text(item) for item in val if item)
    if isinstance(val, dict):
        if "text" in val and isinstance(val["text"], str):
            return val["text"]
        if "content" in val:
            return _extract_text(val["content"])
        return " ".join(_extract_text(v) for v in val.values() if v)
    return str(val) if val is not None else ""


def _detect_unsupported_location(text: str) -> bool:
    """
    Return True if text contains a Vietnamese location that is
    explicitly NOT in the HCMC dataset.

    Only triggers for well-known non-HCMC cities / provinces
    to avoid false positives.
    """
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
        import re
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


def _is_useless_answer(answer: str) -> bool:
    """
    Kiểm tra câu trả lời rỗng, chỉ có citation,
    hoặc chỉ trả fallback.
    """

    if not answer or not answer.strip():
        return True

    text = answer.strip()

    if FALLBACK_TEXT.lower() in text.lower():
        return True
        
    if "thông tin trong chưa đủ" in text.lower() or "chưa đủ để trả lời" in text.lower():
        return True

    # Ví dụ: [EC_001]
    citation_only = re.fullmatch(
        r"\s*\[?EC_\d{3}\]?\s*[.!]?\s*",
        text,
        flags=re.IGNORECASE,
    )

    if citation_only:
        return True

    # Quá ngắn thì cũng coi là không hữu ích
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
    generator: Callable[[str], str] = generate_hybrid,
) -> AnswerResponse:
    """
    Run the complete AI Core / RAG pipeline.
    """
    _ = session_id

    if isinstance(query, (list, dict)):
        query = _extract_text(query)
    elif not isinstance(query, str):
        query = str(query) if query is not None else ""

    if not query or not query.strip():
        return AnswerResponse(
            answer="",
            claims=[],
            needs_clarification=False,
            clarification_question=None,
        )

    if context is None:
        context = {}

    # ---------------------------------------------------------
    # Issue #7 — Out-of-scope location detection
    # Check query AND recent history for non-HCMC location references.
    # ---------------------------------------------------------
    recent_messages = context.get("recent_messages", [])
    history_texts = []
    for m in recent_messages:
        if isinstance(m, dict):
            history_texts.append(_extract_text(m.get("content", "")))
        elif isinstance(m, (list, tuple)):
            history_texts.append(" ".join(_extract_text(item) for item in m))
        elif isinstance(m, str):
            history_texts.append(m)

    full_text_for_location = query + " " + " ".join(history_texts)
    if _detect_unsupported_location(full_text_for_location):
        print(
            f"[pipeline] Unsupported location detected in: "
            f"{full_text_for_location[:100]!r}"
        )
        return AnswerResponse(
            answer=LOCATION_NOT_SUPPORTED_TEXT,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
        )

    # ---------------------------------------------------------
    # Multi-agent preprocessing
    # ---------------------------------------------------------

    # 1. Read conversation history.
    history = history_reader(context)

    # 2. Retrieve lightweight procedure/topic hints.
    procedure_hint = procedure_reader(
        query=query,
        context=context,
        top_k=2,
    )

    # 3. Synthesize the query using history + procedure hints.
    consolidated = synthesizer(
        query=query,
        history=history,
        procedure_hint=procedure_hint,
        generator=generator,
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
        )

    # ---------------------------------------------------------
    # Official RAG pipeline
    # ---------------------------------------------------------

    # 1. Retrieval using resolved query
    retrieved_chunks = retrieve(
        query=consolidated.resolved_query,
        context=context,
    )

    if not retrieved_chunks:
        return AnswerResponse(
            answer=FALLBACK_TEXT,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
        )

    # Issue #1 — Relevance threshold gate.
    # If the best retrieval score is below MIN_RETRIEVAL_SCORE, skip
    # generation entirely and return FALLBACK_TEXT to avoid hallucination.
    top_score = retrieved_chunks[0].retrieval_score
    if top_score < cfg.MIN_RETRIEVAL_SCORE:
        print(
            f"[pipeline] Top-1 score {top_score:.3f} < "
            f"MIN_RETRIEVAL_SCORE {cfg.MIN_RETRIEVAL_SCORE} → FALLBACK"
        )
        return AnswerResponse(
            answer=FALLBACK_TEXT,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
        )

    # 2. Rerank
    ranked_chunks = rerank(retrieved_chunks)

    # 3. Build evidence
    evidence_candidates = build_evidence_candidates(ranked_chunks)

    if not evidence_candidates:
        return AnswerResponse(
            answer=FALLBACK_TEXT,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
        )

    # 4. Prompt Builder
    prompt = build_prompt(
        query=consolidated.resolved_query,
        evidence_candidates=evidence_candidates,
        context=context,
    )

    # 5. Final Answer Generation
    try:
        generated_answer = generator(prompt)
    except Exception as exc:
        print("GENERATOR ERROR:", repr(exc))
        generated_answer = ""

    # 6. Fallback if useless answer
    if _is_useless_answer(generated_answer):
        from rag.prompt_builder import _detect_field_types
        field_types = _detect_field_types(consolidated.resolved_query)
        generated_answer = _answer_from_evidence(evidence_candidates, field_types)

    # 7. Verification
    verification_results = verify_answer(
        generated_answer=generated_answer,
        evidence_candidates=evidence_candidates,
    )

    # 8. Mapper
    verified_claims = map_verification_results(
        verification_results=verification_results,
        evidence_candidates=evidence_candidates,
    )

    return AnswerResponse(
        answer=generated_answer,
        claims=verified_claims,
        needs_clarification=False,
        clarification_question=None,
    )