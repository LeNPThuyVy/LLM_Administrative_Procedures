from dataclasses import dataclass

from rag.evidence_builder import EvidenceCandidate


@dataclass
class VerificationResult:
    claim: str
    evidence_ids: list[str]
    status: str
    reason: str


def _split_into_claims(answer: str) -> list[str]:
    """
    Split the generated answer into simple claims.

    This is only a PoC. Claims are split by sentence-ending punctuation.
    """
    claims: list[str] = []

    for sentence in answer.replace("!", ".").replace("?", ".").split("."):
        claim = sentence.strip()

        if claim:
            claims.append(claim)

    return claims


def _calculate_word_overlap(
    claim: str,
    content: str,
) -> float:
    """
    Calculate a simple word-overlap ratio between claim and evidence.

    This is a lightweight heuristic for the PoC.
    """
    claim_words = set(claim.lower().split())
    evidence_words = set(content.lower().split())

    if not claim_words:
        return 0.0

    matched_words = claim_words.intersection(evidence_words)

    return len(matched_words) / len(claim_words)


def verify_answer(
    generated_answer: str,
    evidence_candidates: list[EvidenceCandidate],
) -> list[VerificationResult]:
    """
    Verify whether the generated answer is supported by the provided evidence.

    This PoC uses simple word overlap.
    """

    if not generated_answer.strip():
        return []

    claims = _split_into_claims(generated_answer)

    results: list[VerificationResult] = []

    for claim in claims:
        best_score = 0.0
        best_evidence_id: str | None = None

        for evidence in evidence_candidates:
            score = _calculate_word_overlap(
                claim=claim,
                content=evidence.content,
            )

            if score > best_score:
                best_score = score
                best_evidence_id = evidence.candidate_id

        if best_score >= 0.5:
            status = "supported"
            reason = (
                "The claim has sufficient word overlap "
                "with the provided evidence."
            )
            evidence_ids = [best_evidence_id] if best_evidence_id else []

        elif best_score >= 0.2:
            status = "partial"
            reason = (
                "The claim has limited word overlap "
                "with the provided evidence."
            )
            evidence_ids = [best_evidence_id] if best_evidence_id else []

        else:
            status = "unsupported"
            reason = (
                "No sufficient evidence was found "
                "to support the claim."
            )
            evidence_ids = []

        results.append(
            VerificationResult(
                claim=claim,
                evidence_ids=evidence_ids,
                status=status,
                reason=reason,
            )
        )

    return results