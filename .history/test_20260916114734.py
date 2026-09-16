from dataclasses import dataclass
from unittest.mock import Mock, patch

from rag.evidence_builder import EvidenceCandidate
from rag.mapper import AnswerResponse, Citation, VerifiedClaim
from rag.pipeline import answer_query
from rag.retrieval import RetrievedChunk
from rag.synthesizer import ConsolidatedQuery
from rag.verification import VerificationResult


def make_chunk(
    chunk_id: str = "CH_001",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="DOC_001",
        content="Thông tin thủ tục hành chính.",
        retrieval_score=0.9,
        metadata={
            "title": "Thủ tục hành chính",
            "document_type": "procedure",
        },
    )


def make_evidence() -> EvidenceCandidate:
    return EvidenceCandidate(
        candidate_id="EC_001",
        chunk_id="CH_001",
        document_id="DOC_001",
        content="Thông tin thủ tục hành chính.",
        title="Thủ tục hành chính",
        document_type="procedure",
        page=None,
        source_url=None,
        retrieval_score=0.9,
        rerank_score=0.9,
    )


def make_claim() -> VerifiedClaim:
    return VerifiedClaim(
        claim="Đây là thông tin được xác minh.",
        status="supported",
        reason="Supported by evidence.",
        citations=[],
    )


# =========================================================
# TEST 1 — Clear query
# =========================================================

def test_clear_query() -> None:
    """Test normal pipeline flow for a clear query."""

    query = "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?"

    context = {}

    resolved_query = (
        "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?"
    )

    # ---------------------------------------------------------
    # Fake generator
    # ---------------------------------------------------------
    #
    # In this pipeline unit test, synthesizer is mocked.
    # Therefore generator is only used for final answer generation.
    #
    fake_generator = Mock(
        return_value="FAKE ANSWER"
    )

    # ---------------------------------------------------------
    # Fake history
    # ---------------------------------------------------------

    fake_history = {
        "recent_messages": [],
        "conversation_summary": "",
    }

    # ---------------------------------------------------------
    # Fake procedure hint
    # ---------------------------------------------------------

    fake_procedure_hint = [
        make_chunk("HINT_001"),
    ]

    # ---------------------------------------------------------
    # Fake ConsolidatedQuery
    # ---------------------------------------------------------

    fake_consolidated = ConsolidatedQuery(
        resolved_query=resolved_query,
        original_query=query,
        needs_clarification=False,
        clarification_question=None,
    )

    # ---------------------------------------------------------
    # Fake official retrieval result
    # ---------------------------------------------------------

    fake_retrieved = [
        make_chunk("CHUNK_001"),
    ]

    # ---------------------------------------------------------
    # Fake reranking result
    # ---------------------------------------------------------

    fake_ranked = [
        make_chunk("CHUNK_001"),
    ]

    # ---------------------------------------------------------
    # Fake evidence candidates
    # ---------------------------------------------------------

    fake_evidence = [
        make_evidence(),
    ]

    # ---------------------------------------------------------
    # Fake verification result
    # ---------------------------------------------------------

    fake_verification = [
        VerificationResult(
            claim="Đây là thông tin được xác minh.",
            evidence_ids=["EC_001"],
            status="supported",
            reason="Supported by evidence.",
        )
    ]

    # ---------------------------------------------------------
    # Fake mapped claims
    # ---------------------------------------------------------

    fake_claims = [
        make_claim(),
    ]

    # ---------------------------------------------------------
    # Mock pipeline dependencies
    # ---------------------------------------------------------

    with (
        patch(
            "rag.pipeline.history_reader",
            return_value=fake_history,
        ) as mock_history_reader,

        patch(
            "rag.pipeline.procedure_reader",
            return_value=fake_procedure_hint,
        ) as mock_procedure_reader,

        patch(
            "rag.pipeline.synthesizer",
            return_value=fake_consolidated,
        ) as mock_synthesizer,

        patch(
            "rag.pipeline.retrieve",
            return_value=fake_retrieved,
        ) as mock_retrieve,

        patch(
            "rag.pipeline.rerank",
            return_value=fake_ranked,
        ) as mock_rerank,

        patch(
            "rag.pipeline.build_evidence_candidates",
            return_value=fake_evidence,
        ) as mock_evidence_builder,

        patch(
            "rag.pipeline.build_prompt",
            return_value="FINAL PROMPT",
        ) as mock_prompt_builder,

        patch(
            "rag.pipeline.verify_answer",
            return_value=fake_verification,
        ) as mock_verify,

        patch(
            "rag.pipeline.map_verification_results",
            return_value=fake_claims,
        ) as mock_mapper,
    ):

        # -----------------------------------------------------
        # Run pipeline
        # -----------------------------------------------------

        result = answer_query(
            query=query,
            session_id="session-001",
            context=context,
            generator=fake_generator,
        )

    # =========================================================
    # 1. Check AnswerResponse
    # =========================================================

    assert isinstance(result, AnswerResponse)

    assert result.answer == "FAKE ANSWER"

    assert result.claims == fake_claims

    assert result.needs_clarification is False

    assert result.clarification_question is None

    # =========================================================
    # 2. Check history_reader
    # =========================================================

    mock_history_reader.assert_called_once_with(
        context
    )

    # =========================================================
    # 3. Check procedure_reader
    # =========================================================

    mock_procedure_reader.assert_called_once_with(
        query=query,
        context=context,
        top_k=2,
    )

    # =========================================================
    # 4. Check synthesizer
    # =========================================================

    mock_synthesizer.assert_called_once_with(
        query=query,
        history=fake_history,
        procedure_hint=fake_procedure_hint,
        generator=fake_generator,
    )

    # =========================================================
    # 5. CRITICAL:
    # Official retrieval MUST use resolved_query
    # =========================================================

    mock_retrieve.assert_called_once_with(
        query=resolved_query,
        context=context,
    )

    # Make sure original query was NOT used for official retrieval.
    assert (
        mock_retrieve.call_args.kwargs["query"]
        == resolved_query
    )

    assert (
        mock_retrieve.call_args.kwargs["query"]
        != query
        or resolved_query == query
    )

    # =========================================================
    # 6. Check reranking
    # =========================================================

    mock_rerank.assert_called_once_with(
        fake_retrieved
    )

    # =========================================================
    # 7. Check evidence builder
    # =========================================================

    mock_evidence_builder.assert_called_once_with(
        fake_ranked
    )

    # =========================================================
    # 8. Check prompt builder
    # =========================================================

    mock_prompt_builder.assert_called_once_with(
        query=resolved_query,
        evidence_candidates=fake_evidence,
        context=context,
    )

    # =========================================================
    # 9. Check final answer generation
    # =========================================================

    fake_generator.assert_called_once_with(
        "FINAL PROMPT"
    )

    # =========================================================
    # 10. Check verification
    # =========================================================

    mock_verify.assert_called_once_with(
        generated_answer="FAKE ANSWER",
        evidence_candidates=fake_evidence,
    )

    # =========================================================
    # 11. Check mapper
    # =========================================================

    mock_mapper.assert_called_once_with(
        verification_results=fake_verification,
        evidence_candidates=fake_evidence,
    )

    print("TEST 1 PASS — Clear query")

# =========================================================
# TEST 2 — Clarification
# =========================================================

def test_clarification() -> None:
    query = "Giấy tờ."

    fake_generator = Mock(
        return_value=(
            """
            {
                "resolved_query": "",
                "needs_clarification": true,
                "clarification_question":
                    "Bạn muốn hỏi giấy tờ của thủ tục nào?"
            }
            """
        )
    )

    consolidated = ConsolidatedQuery(
        resolved_query="",
        original_query=query,
        needs_clarification=True,
        clarification_question=(
            "Bạn muốn hỏi giấy tờ của thủ tục nào?"
        ),
    )

    with (
        patch(
            "rag.pipeline.history_reader",
            return_value={
                "recent_messages": [],
                "conversation_summary": "",
            },
        ),
        patch(
            "rag.pipeline.procedure_reader",
            return_value=[],
        ),
        patch(
            "rag.pipeline.synthesizer",
            return_value=consolidated,
        ) as mock_synthesizer,
        patch(
            "rag.pipeline.retrieve",
        ) as mock_retrieve,
        patch(
            "rag.pipeline.rerank",
        ) as mock_rerank,
        patch(
            "rag.pipeline.build_evidence_candidates",
        ) as mock_evidence_builder,
        patch(
            "rag.pipeline.build_prompt",
        ) as mock_prompt_builder,
        patch(
            "rag.pipeline.verify_answer",
        ) as mock_verify,
        patch(
            "rag.pipeline.map_verification_results",
        ) as mock_mapper,
    ):
        result = answer_query(
            query=query,
            session_id="session-002",
            context={},
            generator=fake_generator,
        )

    mock_synthesizer.assert_called_once()

    # Official RAG pipeline must NOT run.
    mock_retrieve.assert_not_called()
    mock_rerank.assert_not_called()
    mock_evidence_builder.assert_not_called()
    mock_prompt_builder.assert_not_called()
    mock_verify.assert_not_called()
    mock_mapper.assert_not_called()

    # Clarification response
    assert isinstance(result, AnswerResponse)
    assert result.answer is None
    assert result.claims == []
    assert result.needs_clarification is True
    assert result.clarification_question == (
        "Bạn muốn hỏi giấy tờ của thủ tục nào?"
    )

    # Only synthesizer LLM call.
    assert fake_generator.call_count == 0

    print ("TEST 2 PASS")


def test_multi_turn() -> None:
    query = "Giấy tờ."

    context = {
        "recent_messages": [
            {
                "role": "user",
                "content": (
                    "Tôi muốn đăng ký hộ kinh doanh ở Bình Dương."
                ),
            },
            {
                "role": "assistant",
                "content": "Bạn muốn biết thông tin gì?",
            },
        ],
        "conversation_summary": "",
    }

    resolved_query = (
        "Tôi cần biết giấy tờ để đăng ký hộ kinh doanh ở Bình Dương."
    )

    fake_generator = Mock(
        side_effect=[
            "synthesizer output",
            "final answer",
        ]
    )

    consolidated = ConsolidatedQuery(
        resolved_query=resolved_query,
        original_query=query,
        needs_clarification=False,
        clarification_question=None,
    )

    fake_retrieved = [
        make_chunk(),
    ]

    fake_ranked = [
        make_chunk(),
    ]

    fake_evidence = [
        make_evidence(),
    ]

    fake_verification = [
        VerificationResult(
            claim="final answer",
            evidence_ids=["EC_001"],
            status="supported",
            reason="Supported by evidence.",
        )
    ]

    fake_claims = [
        make_claim(),
    ]

    with (
        patch(
            "rag.pipeline.history_reader",
            return_value={
                "recent_messages": context["recent_messages"],
                "conversation_summary": "",
            },
        ),
        patch(
            "rag.pipeline.procedure_reader",
            return_value=[],
        ),
        patch(
            "rag.pipeline.synthesizer",
            return_value=consolidated,
        ),
        patch(
            "rag.pipeline.retrieve",
            return_value=fake_retrieved,
        ) as mock_retrieve,
        patch(
            "rag.pipeline.rerank",
            return_value=fake_ranked,
        ),
        patch(
            "rag.pipeline.build_evidence_candidates",
            return_value=fake_evidence,
        ),
        patch(
            "rag.pipeline.build_prompt",
            return_value="FINAL PROMPT",
        ),
        patch(
            "rag.pipeline.verify_answer",
            return_value=fake_verification,
        ),
        patch(
            "rag.pipeline.map_verification_results",
            return_value=fake_claims,
        ),
    ):
        result = answer_query(
            query=query,
            session_id="session-003",
            context=context,
            generator=fake_generator,
        )

    # The official retrieval MUST use resolved_query.
    mock_retrieve.assert_called_once_with(
        query=resolved_query,
        context=context,
    )

    assert isinstance(result, AnswerResponse)
    assert result.needs_clarification is False
    assert result.clarification_question is None

    print ("TEST 3 PASS")

test_clear_query()
test_clarification()
test_multi_turn()