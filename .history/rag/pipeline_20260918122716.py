import re
from collections.abc import Callable

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


def _answer_from_evidence(evidence_candidates):
    """
    Nếu LLM không tạo được câu trả lời hữu ích,
    dùng trực tiếp evidence tốt nhất.
    """

    if not evidence_candidates:
        return FALLBACK_TEXT

    best = evidence_candidates[0]

    content = (best.content or "").strip()

    if not content:
        return FALLBACK_TEXT

    return f"{content} [{best.candidate_id}]"


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
        generated_answer = _answer_from_evidence(evidence_candidates)

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