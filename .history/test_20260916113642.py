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
    query = "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?"

    fake_generator = Mock(
        side_effect=[
            """
            {
                "resolved_query": "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?",
                "needs_clarification": false,
                "clarification_question": null
            }
            """,
            "Bạn cần chuẩn bị các giấy tờ sau: ...",
        ]
    )

    fake_history = {
        "recent_messages": [],
        "conversation_summary": "",
    }

    fake_procedure_hint = [
        make_chunk("HINT_001"),
    ]

    fake_retrieved = [
        make_chunk("CH_001"),
    ]

    fake_ranked = [
        make_chunk("CH_001"),
    ]

    fake_evidence = [
        make_evidence(),
    ]

    fake_verification = [
        VerificationResult(
            claim="Đây là thông tin được xác minh.",
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
            return_value=fake_history,
        ) as mock_history_reader,
        patch(
            "rag.pipeline.procedure_reader",
            return_value=fake_procedure_hint,
        ) as mock_procedure_reader,
        patch(
            "rag.pipeline.synthesizer",
            return_value=ConsolidatedQuery(
                resolved_query=(
                    "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?"
                ),
                original_query=query,
                needs_clarification=False,
                clarification_question=None,
            ),
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
        result = answer_query(
            query=query,
            session_id="session-001",
            context={},
            generator=fake_generator,
        )

    # Multi-agent preprocessing
    mock_history_reader.assert_called_once_with({})
    mock_procedure_reader.assert_called_once_with(
        query=query,
        context={},
        top_k=2,
    )

    mock_synthesizer.assert_called_once()

    # Official retrieval must use resolved query.
    mock_retrieve.assert_called_once_with(
        query=(
            "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?"
        ),
        context={},
    )

    # Existing RAG flow must continue.
    mock_rerank.assert_called_once_with(fake_retrieved)
    mock_evidence_builder.assert_called_once_with(fake_ranked)
    mock_prompt_builder.assert_called_once_with(
        query=(
            "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?"
        ),
        evidence_candidates=fake_evidence,
        context={},
    )
    mock_verify.assert_called_once()
    mock_mapper.assert_called_once()

    # Normal response
    assert isinstance(result, AnswerResponse)
    assert result.needs_clarification is False
    assert result.clarification_question is None
    assert result.answer == "Bạn cần chuẩn bị các giấy tờ sau: ..."

    # Synthesizer + final answer = 2 LLM calls
    assert fake_generator.call_count == 2


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

test_clear_query()
