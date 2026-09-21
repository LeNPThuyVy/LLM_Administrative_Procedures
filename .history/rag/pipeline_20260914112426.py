from collections.abc import Callable

from rag.evidence_builder import build_evidence_candidates
from rag.generator import generate_answer
from rag.mapper import AnswerResponse, map_verification_results
from rag.prompt_builder import build_prompt
from rag.rerank import rerank
from rag.retrieval import retrieve
from rag.verification import verify_answer


def answer_query(
    query: str,
    context: dict | None = None,
    generator: Callable[[str], str] = generate_answer,
) -> AnswerResponse:
    """
    Run the complete AI Core RAG pipeline.
    """

    # Empty query: return a valid empty response.
    if not query or not query.strip():
        return AnswerResponse(
            answer="",
            claims=[],
        )

    #Retrieval
    retrieved_chunks = retrieve(
        query=query,
        context=context,
    )

    #Reranking
    ranked_chunks = rerank(query, retrieved_chunks)

    #Evidence Builder
    evidence_candidates = build_evidence_candidates(
        ranked_chunks
    )

    #Prompt Builder
    prompt = build_prompt(
        query=query,
        evidence_candidates=evidence_candidates,
        context=context,
    )

    #LLM Generation
    generated_answer = generator(prompt)

    #Verification
    verification_results = verify_answer(
        generated_answer=generated_answer,
        evidence_candidates=evidence_candidates,
    )

    #Mapper
    verified_claims = map_verification_results(
        verification_results=verification_results,
        evidence_candidates=evidence_candidates,
    )

    #Final response
    return AnswerResponse(
        answer=generated_answer,
        claims=verified_claims,
    )