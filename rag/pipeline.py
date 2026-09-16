import re
from collections.abc import Callable

from rag.evidence_builder import build_evidence_candidates
from rag.generator import generate_answer
from rag.mapper import AnswerResponse, map_verification_results
from rag.prompt_builder import build_prompt
from rag.rerank import rerank
from rag.retrieval import retrieve
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
    context: dict | None = None,
    generator: Callable[[str], str] = generate_answer,
) -> AnswerResponse:
    """
    Run complete RAG pipeline.
    """

    if not query or not query.strip():
        return AnswerResponse(
            answer="",
            claims=[],
        )

    if context is None:
        context = {}

    # 1. Retrieval
    retrieved_chunks = retrieve(
        query=query,
        context=context,
    )

    print("\n========== RETRIEVAL DEBUG ==========")
    print("Query:", query)
    print("So chunk tim duoc:", len(retrieved_chunks))

    for chunk in retrieved_chunks:
        print("-------------------------------------")
        print("Chunk ID:", chunk.chunk_id)
        print("Document ID:", chunk.document_id)
        print("Score:", chunk.retrieval_score)
        print("Title:", chunk.metadata.get("title", ""))
        print("Content:", chunk.content)

    print("=====================================\n")

    if not retrieved_chunks:
        return AnswerResponse(
            answer=FALLBACK_TEXT,
            claims=[],
        )

    # 2. Rerank
    ranked_chunks = rerank(
        retrieved_chunks
    )

    # 3. Build evidence
    evidence_candidates = build_evidence_candidates(
        ranked_chunks
    )

    if not evidence_candidates:
        return AnswerResponse(
            answer=FALLBACK_TEXT,
            claims=[],
        )

    # 4. Build prompt
    prompt = build_prompt(
        query=query,
        evidence_candidates=evidence_candidates,
        context=context,
    )

    # 5. Generate
    try:
        generated_answer = generator(prompt)
    except Exception as exc:
        print(
            "GENERATOR ERROR:",
            repr(exc)
        )

        generated_answer = ""

    # 6. Không chấp nhận câu chỉ có [EC_001]
    if _is_useless_answer(
        generated_answer
    ):
        print(
            "LLM answer khong huu ich. "
            "Dang dung truc tiep evidence."
        )

        generated_answer = _answer_from_evidence(
            evidence_candidates
        )

    print("\n========== FINAL ANSWER ==========")
    print(generated_answer)
    print("==================================\n")

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
    )