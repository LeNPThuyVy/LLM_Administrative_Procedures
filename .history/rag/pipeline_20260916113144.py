from collections.abc import Callable

from rag.evidence_builder import build_evidence_candidates
from rag.generator import generate_answer
from rag.history_reader import history_reader
from rag.mapper import AnswerResponse, map_verification_results
from rag.procedure_reader import procedure_reader
from rag.prompt_builder import build_prompt
from rag.rerank import rerank
from rag.retrieval import retrieve
from rag.synthesizer import synthesizer
from rag.verification import verify_answer


def answer_query(
    query: str,
    session_id: str,
    context: dict | None = None,
    generator: Callable[[str], str] = generate_answer,
) -> AnswerResponse:
    """
    Run the complete AI Core pipeline.

    Day 1 flow:

        query
            ↓
        history_reader
            ↓
        procedure_reader
            ↓
        synthesizer
            ↓
        clarification OR resolved_query
            ↓
        official retrieval
            ↓
        rerank
            ↓
        evidence builder
            ↓
        prompt builder
            ↓
        answer generation
            ↓
        verification
            ↓
        mapper
            ↓
        AnswerResponse

    Args:
        query: Current user query.
        session_id: Conversation/session identifier.
        context: Conversation context.
        generator: Injected LLM generator for testing and generation.

    Returns:
        AnswerResponse.
    """

    # session_id is part of the AI Core contract.
    # Day 1 does not require it for retrieval logic yet.
    _ = session_id

    # ---------------------------------------------------------
    # Empty query
    # ---------------------------------------------------------
    # Preserve the existing behavior: do not call LLM/retrieval
    # for an empty query.
    if not query or not query.strip():
        return AnswerResponse(
            answer="",
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
    #
    # This is intentionally a separate retrieval call from the
    # official retrieval below.
    procedure_hint = procedure_reader(
        query=query,
        context=context,
        top_k=2,
    )

    # 3. Synthesize the query using history + procedure hints.
    #
    # The same injected generator is used for the synthesizer
    # and the final answer generation.
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

    # Use the resolved query for the official retrieval.
    retrieved_chunks = retrieve(
        query=consolidated.resolved_query,
        context=context,
    )

    # Reranking
    ranked_chunks = rerank(retrieved_chunks)

    # Evidence Builder
    evidence_candidates = build_evidence_candidates(
        ranked_chunks
    )

    # Prompt Builder
    prompt = build_prompt(
        query=consolidated.resolved_query,
        evidence_candidates=evidence_candidates,
        context=context,
    )

    # Final Answer Generation
    generated_answer = generator(prompt)

    # Verification
    verification_results = verify_answer(
        generated_answer=generated_answer,
        evidence_candidates=evidence_candidates,
    )

    # Mapper
    verified_claims = map_verification_results(
        verification_results=verification_results,
        evidence_candidates=evidence_candidates,
    )

    # Final response
    return AnswerResponse(
        answer=generated_answer,
        claims=verified_claims,
        needs_clarification=False,
        clarification_question=None,
    )