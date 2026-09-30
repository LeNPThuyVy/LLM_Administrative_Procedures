import re
from dataclasses import dataclass

from rag.evidence_builder import EvidenceCandidate


@dataclass
class VerificationResult:
    claim: str
    evidence_ids: list[str]
    status: str
    reason: str


VIETNAMESE_STOPWORDS = {
    "là", "của", "và", "những", "các", "cho", "theo", "tại", "với", "được",
    "khi", "cần", "phải", "trường", "hợp", "nếu", "hoặc", "có", "trong", "để"
}


def _split_into_claims(answer: str) -> list[str]:
    """
    Split the generated answer into simple claims.
    Avoid splitting on common abbreviations (e.g., UBND., TP., etc.).
    """
    if not answer:
        return []

    # Protect common abbreviations before splitting
    text = answer
    abbrevs = ["UBND.", "TP.", "TT.", "QĐ.", "NĐ.", "KTT.", "BTC."]
    for idx, abb in enumerate(abbrevs):
        text = text.replace(abb, f"__ABB_{idx}__")

    # Split by newline or sentence-ending punctuation followed by whitespace
    raw_sentences = re.split(r'(?<=[.!?])\s+|\n+', text)

    claims: list[str] = []
    for sentence in raw_sentences:
        # Restore abbreviations
        for idx, abb in enumerate(abbrevs):
            sentence = sentence.replace(f"__ABB_{idx}__", abb)
        
        claim = sentence.strip()
        if claim:
            claims.append(claim)

    return claims


def _calculate_word_overlap(
    claim: str,
    content: str,
) -> float:
    """
    Calculate word-overlap ratio between claim and evidence, filtering stop words.
    """
    claim_words = {
        w for w in re.findall(r'\w+', claim.lower())
        if w not in VIETNAMESE_STOPWORDS
    }
    evidence_words = {
        w for w in re.findall(r'\w+', content.lower())
        if w not in VIETNAMESE_STOPWORDS
    }

    if not claim_words:
        return 0.0

    matched_words = claim_words.intersection(evidence_words)

    return len(matched_words) / len(claim_words)


def _extract_numbers_from_text(text: str) -> set[str]:
    """
    Extract normalized numbers/quantities from text (excluding candidate IDs like EC_001).
    Normalizes numbers: e.g., '50.000' -> '50000', '03' -> '3'.
    """
    if not text:
        return set()

    # Strip citations like [EC_001]
    cleaned = re.sub(r'\[?EC_\d{3}\]?', '', text, flags=re.IGNORECASE)

    # Find sequences of digits, possibly with separators
    raw_nums = re.findall(r'\b\d+(?:[.,]\d+)*\b', cleaned)
    normalized = set()
    for num_str in raw_nums:
        pure_digits = num_str.replace('.', '').replace(',', '')
        if pure_digits:
            try:
                norm_val = str(int(pure_digits))
                normalized.add(norm_val)
            except ValueError:
                pass

    return normalized


def _check_number_conflict(claim: str, evidence_content: str) -> bool:
    """
    Return True if claim contains numbers that are NOT present in the candidate evidence.
    """
    claim_nums = _extract_numbers_from_text(claim)
    if not claim_nums:
        return False

    evidence_nums = _extract_numbers_from_text(evidence_content)
    missing_nums = claim_nums - evidence_nums
    return len(missing_nums) > 0


def verify_answer(
    generated_answer: str,
    evidence_candidates: list[EvidenceCandidate],
) -> list[VerificationResult]:
    """
    Verify whether the generated answer is supported by the provided evidence.
    Includes Number/Date/Fee verification to catch numerical hallucinations.
    """

    if not generated_answer.strip():
        return []

    claims = _split_into_claims(generated_answer)

    results: list[VerificationResult] = []

    candidate_ids = {c.candidate_id for c in evidence_candidates}
    evidence_map = {c.candidate_id: c for c in evidence_candidates}

    for claim in claims:
        best_score = 0.0
        best_evidence_id: str | None = None

        # Check for explicit candidate_id citation in claim e.g. [EC_001]
        explicit_matches = re.findall(r'\[?(EC_\d{3})\]?', claim)
        valid_explicit = [eid for eid in explicit_matches if eid in candidate_ids]

        if valid_explicit:
            best_evidence_id = valid_explicit[0]
            best_score = 1.0
        else:
            for evidence in evidence_candidates:
                score = _calculate_word_overlap(
                    claim=claim,
                    content=evidence.content,
                )

                if score > best_score:
                    best_score = score
                    best_evidence_id = evidence.candidate_id

        # Number & Quantity Verification Layer
        has_num_conflict = False
        if best_evidence_id and best_evidence_id in evidence_map:
            target_evidence = evidence_map[best_evidence_id]
            has_num_conflict = _check_number_conflict(claim, target_evidence.content)

        if has_num_conflict:
            status = "unsupported"
            reason = (
                "Số liệu, chi phí hoặc thời hạn trong câu không khớp với bằng chứng."
            )
            evidence_ids = []
        elif best_score >= 0.35:
            status = "supported"
            reason = (
                "The claim is supported by the provided evidence."
            )
            evidence_ids = [best_evidence_id] if best_evidence_id else []

        elif best_score >= 0.15:
            status = "partial"
            reason = (
                "The claim has limited word overlap with the provided evidence."
            )
            evidence_ids = [best_evidence_id] if best_evidence_id else []

        else:
            status = "unsupported"
            reason = (
                "The claim has insufficient word overlap with any provided evidence."
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