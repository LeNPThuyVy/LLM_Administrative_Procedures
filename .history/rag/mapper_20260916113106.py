from dataclasses import dataclass

from rag.evidence_builder import EvidenceCandidate
from rag.verification import VerificationResult


@dataclass
class Citation:
    evidence_id: str
    document_id: str
    chunk_id: str
    title: str
    source_url: str | None


@dataclass
class VerifiedClaim:
    claim: str
    status: str
    reason: str
    citations: list[Citation]


@dataclass
@dataclass
class AnswerResponse:
    answer: str | None
    claims: list[VerifiedClaim]
    needs_clarification: bool = False
    clarification_question: str | None = None


def map_verification_results(
    verification_results: list[VerificationResult],
    evidence_candidates: list[EvidenceCandidate],
) -> list[VerifiedClaim]:
    """
    Map verification results to application/UI response objects.
    """

    evidence_map: dict[str, EvidenceCandidate] = {
        candidate.candidate_id: candidate
        for candidate in evidence_candidates
    }

    verified_claims: list[VerifiedClaim] = []

    for result in verification_results:
        citations: list[Citation] = []

        for evidence_id in result.evidence_ids:
            evidence = evidence_map.get(evidence_id)

            if evidence is None:
                continue

            source_url = evidence.source_url

            if not source_url:
                source_url = None

            citation = Citation(
                evidence_id=evidence.candidate_id,
                document_id=evidence.document_id,
                chunk_id=evidence.chunk_id,
                title=evidence.title,
                source_url=source_url,
            )

            citations.append(citation)

        verified_claim = VerifiedClaim(
            claim=result.claim,
            status=result.status,
            reason=result.reason,
            citations=citations,
        )

        verified_claims.append(verified_claim)

    return verified_claims