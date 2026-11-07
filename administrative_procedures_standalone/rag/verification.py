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
    "khi", "cần", "phải", "trường", "hợp", "nếu", "hoặc", "có", "trong", "để",
    "về", "như", "sau", "này", "đó", "thì", "một", "số", "bạn", "tôi"
}


# Khớp đúng dạng mà _extract_numbers_from_text bỏ qua ở đầu dòng.
_LIST_MARKER_ONLY = re.compile(r'^(?:-\s*)?\d{1,2}[.)]$')


def _split_into_claims(answer: str) -> list[str]:
    """
    Split the generated answer into simple claims.
    Avoid splitting on common abbreviations (e.g., UBND., TP., etc.).
    """
    if not answer:
        return []

    # Protect common abbreviations before splitting
    text = answer
    abbrevs = ["UBND.", "TP.", "TT.", "QĐ.", "NĐ.", "KTT.", "BTC.", "P.", "Q."]
    for idx, abb in enumerate(abbrevs):
        text = text.replace(abb, f"__ABB_{idx}__")

    # Protect thousand separators in numbers like 50.000 before splitting
    text = re.sub(r'(\d)\.(\d{3})\b', r'\1__DOT__\2', text)

    # Split by newline or sentence-ending punctuation followed by whitespace
    raw_sentences = re.split(r'(?<=[.!?])\s+|\n+', text)

    claims: list[str] = []
    pending_marker = ""
    for sentence in raw_sentences:
        # Restore abbreviations and number dots
        for idx, abb in enumerate(abbrevs):
            sentence = sentence.replace(f"__ABB_{idx}__", abb)
        sentence = sentence.replace("__DOT__", ".")

        claim = sentence.strip()
        if not claim:
            continue

        # "2. Giấy tờ" bị tách tại dấu chấm: nếu để "2." thành claim riêng,
        # số thứ tự sẽ bị coi là số liệu sai và làm mất cả câu trả lời.
        if _LIST_MARKER_ONLY.match(claim):
            pending_marker = claim
            continue

        claims.append(f"{pending_marker} {claim}" if pending_marker else claim)
        pending_marker = ""

    return claims


def _tokenize_meaningful(text: str) -> list[str]:
    """Tokenize lowercase words excluding [EC_xxx] tags and Vietnamese stopwords."""
    cleaned = re.sub(r'\[?EC_\d{3}\]?', ' ', text or "", flags=re.IGNORECASE)
    cleaned = re.sub(r'(?:^|\n)\s*(?:-\s*)?\d+[.)]\s+', ' ', cleaned)
    tokens = re.findall(r'\w+', cleaned.lower())
    return [w for w in tokens if w not in VIETNAMESE_STOPWORDS]


def _calculate_word_overlap(
    claim: str,
    content: str,
) -> float:
    """
    Calculate word-overlap ratio between claim and evidence, filtering stop words.
    """
    claim_words = set(_tokenize_meaningful(claim))
    evidence_words = set(_tokenize_meaningful(content))

    if not claim_words:
        return 0.0

    matched_words = claim_words.intersection(evidence_words)

    return len(matched_words) / len(claim_words)


def _calculate_bigram_overlap(claim: str, content: str) -> float:
    """Calculate contiguous bigram overlap ratio on meaningful tokens."""
    c_tokens = _tokenize_meaningful(claim)
    e_tokens = _tokenize_meaningful(content)
    if len(c_tokens) < 2 or len(e_tokens) < 2:
        return 0.0
    c_bigrams = {(c_tokens[i], c_tokens[i + 1]) for i in range(len(c_tokens) - 1)}
    e_bigrams = {(e_tokens[i], e_tokens[i + 1]) for i in range(len(e_tokens) - 1)}
    if not c_bigrams:
        return 0.0
    return len(c_bigrams.intersection(e_bigrams)) / len(c_bigrams)


def _extract_numbers_from_text(text: str) -> set[str]:
    """
    Extract normalized numbers/quantities from text (excluding candidate IDs like EC_001).
    Normalizes numbers: e.g., '50.000' -> '50000', '03' -> '3'.
    Also maps basic Vietnamese number words to digits.
    """
    if not text:
        return set()

    # Strip citations like [EC_001]
    cleaned = re.sub(r'\[?EC_\d{3}\]?', '', text, flags=re.IGNORECASE)

    # Strip list numbering at start of line (e.g. "1. ", "2) ", "- 1.") and "Bước 1"
    cleaned = re.sub(r'(?:^|\n)\s*(?:-\s*)?\d+[.)]\s+', ' ', cleaned)
    cleaned = re.sub(r'\bbước\s+\d+\b', ' ', cleaned, flags=re.IGNORECASE)

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


def _check_number_conflict(claim: str, evidence_content: str, all_evidence_text: str = "") -> bool:
    """
    Return True if claim contains numbers that are NOT present in the candidate evidence
    (or combined evidence corpus of the same procedure).
    """
    claim_nums = _extract_numbers_from_text(claim)
    if not claim_nums:
        return False

    evidence_nums = _extract_numbers_from_text(evidence_content)
    if all_evidence_text:
        evidence_nums = evidence_nums.union(_extract_numbers_from_text(all_evidence_text))
    missing_nums = claim_nums - evidence_nums
    return len(missing_nums) > 0


def _has_negation_conflict(claim: str, evidence_content: str) -> bool:
    """Detect if claim asserts requirement while evidence negates it."""
    claim_lower = claim.lower().strip()
    ev_lower = evidence_content.lower()

    # Pattern: affirmative requirement statement in claim (cần X, phải X, yêu cầu X, etc.)
    affirmative_triggers = re.findall(
        r'(?:cần|phải|yêu cầu|bắt buộc|cần nộp|cần xuất trình|cần có)\s+(.{4,60}?)(?:[,;.!\n]|$)',
        claim_lower,
    )
    for phrase in affirmative_triggers:
        phrase = phrase.strip()
        if not phrase or len(phrase) < 4:
            continue
        negation_prefixes = [
            "không cần ",
            "không phải ",
            "không cần nộp ",
            "miễn ",
            "không yêu cầu ",
            "không bắt buộc ",
        ]
        for neg in negation_prefixes:
            if (neg + phrase) in claim_lower or (neg + phrase[:20]) in claim_lower:
                continue
            if (neg + phrase) in ev_lower or (neg + phrase[:20]) in ev_lower:
                return True

    # Reverse: claim says "miễn phí / không thu phí" while evidence has concrete fee > 0
    if any(k in claim_lower for k in ("miễn phí", "không thu phí", "không mất phí", "0 đồng")):
        if not any(k in ev_lower for k in ("miễn phí", "không thu phí", "không mất phí", "0 đồng", "không thu", "miễn")):
            ev_nums = _extract_numbers_from_text(ev_lower)
            if any(int(n) >= 1000 for n in ev_nums if n.isdigit()):
                return True

    return False


def _is_structural_header(claim: str) -> bool:
    """Check if a line is just an introductory header like 'Thành phần hồ sơ:' or 'Về thủ tục X, thông tin chi tiết như sau:'."""
    cleaned = re.sub(r'\[?EC_\d{3}\]?', '', claim).strip()
    if cleaned.endswith(":") and len(_tokenize_meaningful(cleaned)) <= 8:
        return True
    if re.match(r'^về\s+.+,\s*thông tin chi tiết như sau:?\s*$', cleaned, flags=re.IGNORECASE):
        return True
    return False


def verify_answer(
    generated_answer: str,
    evidence_candidates: list[EvidenceCandidate],
) -> list[VerificationResult]:
    """
    Verify whether the generated answer is supported by the provided evidence.
    Includes Number/Date/Fee verification, N-gram overlap, and negation checks
    to catch numerical and semantic hallucinations.
    """

    if not generated_answer.strip():
        return []

    claims = _split_into_claims(generated_answer)

    results: list[VerificationResult] = []

    candidate_ids = {c.candidate_id for c in evidence_candidates}
    evidence_map = {c.candidate_id: c for c in evidence_candidates}
    combined_evidence_text = "\n".join(c.content or "" for c in evidence_candidates)

    for claim in claims:
        best_score = 0.0
        best_bigram = 0.0
        best_evidence_id: str | None = None

        # Structural intro/header line that carries no standalone factual assertion
        if _is_structural_header(claim) and evidence_candidates:
            first_id = evidence_candidates[0].candidate_id
            results.append(
                VerificationResult(
                    claim=claim,
                    evidence_ids=[first_id],
                    status="supported",
                    reason="Structural header supported by context.",
                )
            )
            continue

        # Check for explicit candidate_id citation in claim e.g. [EC_001]
        explicit_matches = re.findall(r'\[?(EC_\d{3})\]?', claim)
        valid_explicit = [eid for eid in explicit_matches if eid in candidate_ids]

        if valid_explicit:
            best_evidence_id = valid_explicit[0]
            # Combine content of all explicitly cited evidence in this claim
            cited_contents = " \n ".join(
                evidence_map[eid].content for eid in valid_explicit if eid in evidence_map
            )
            raw_overlap = _calculate_word_overlap(claim=claim, content=cited_contents)
            best_bigram = _calculate_bigram_overlap(claim=claim, content=cited_contents)
            meaningful_tokens = _tokenize_meaningful(claim)

            # Strict: Do NOT grant unconditional +0.25 bonus just for having [EC_xxx].
            # Only grant a modest +0.08 boost when lexical overlap is already solid (>= 0.30)
            # or when the claim is a very short factual label (<= 2 meaningful words, overlap > 0).
            if raw_overlap >= 0.30:
                best_score = raw_overlap + 0.08 + (0.07 if best_bigram >= 0.15 else 0.0)
            elif len(meaningful_tokens) <= 2 and raw_overlap > 0.0:
                best_score = 0.35
            else:
                best_score = raw_overlap
        else:
            for evidence in evidence_candidates:
                score = _calculate_word_overlap(
                    claim=claim,
                    content=evidence.content,
                )
                bg = _calculate_bigram_overlap(
                    claim=claim,
                    content=evidence.content,
                )
                combined_metric = score + (0.07 if bg >= 0.15 else 0.0)

                if combined_metric > best_score:
                    best_score = combined_metric
                    best_bigram = bg
                    best_evidence_id = evidence.candidate_id

            # Also check overlap against combined evidence if single-chunk overlap is partial
            if best_score < 0.35 and evidence_candidates:
                multi_overlap = _calculate_word_overlap(claim=claim, content=combined_evidence_text)
                multi_bg = _calculate_bigram_overlap(claim=claim, content=combined_evidence_text)
                if multi_overlap >= 0.45 and multi_bg >= 0.15:
                    best_score = multi_overlap
                    best_evidence_id = best_evidence_id or evidence_candidates[0].candidate_id

        # Number & Quantity and Negation Verification Layer
        has_num_conflict = False
        has_neg_conflict = False
        if best_evidence_id and best_evidence_id in evidence_map:
            target_evidence = evidence_map[best_evidence_id]
            has_num_conflict = _check_number_conflict(
                claim,
                target_evidence.content,
                all_evidence_text=combined_evidence_text,
            )
            has_neg_conflict = _has_negation_conflict(claim, target_evidence.content)
        else:
            has_num_conflict = _check_number_conflict(claim, combined_evidence_text)

        if has_num_conflict or has_neg_conflict:
            status = "unsupported"
            if has_neg_conflict:
                reason = "Nội dung khẳng định trong câu trái ngược với thông tin phủ định trong bằng chứng (ví dụ: cần/không cần)."
            else:
                reason = (
                    "Số liệu, chi phí hoặc thời hạn trong câu không khớp với bằng chứng."
                )
            evidence_ids = []
        elif best_score >= 0.35:
            status = "supported"
            reason = (
                "The claim is supported by the provided evidence."
            )
            evidence_ids = valid_explicit if valid_explicit else ([best_evidence_id] if best_evidence_id else [])

        elif best_score >= 0.20:
            status = "partial"
            reason = (
                "The claim has limited word overlap with the provided evidence."
            )
            evidence_ids = valid_explicit if valid_explicit else ([best_evidence_id] if best_evidence_id else [])

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


def filter_answer_by_verification(
    generated_answer: str,
    verification_results: list[VerificationResult],
) -> tuple[str, list[VerificationResult], bool]:
    """
    Remove unsupported claims from the final answer in strict mode.

    Returns:
        (filtered_answer, kept_results, has_critical_conflict)
    """
    if not verification_results:
        return "", [], False

    has_critical_conflict = any(
        r.status == "unsupported"
        and (
            "Số liệu" in r.reason
            or "trái ngược" in r.reason
        )
        for r in verification_results
    )

    kept_results: list[VerificationResult] = []
    kept_sentences: list[str] = []

    for r in verification_results:
        if r.status == "supported":
            kept_results.append(r)
            kept_sentences.append(r.claim)
        elif r.status == "partial" and not has_critical_conflict:
            # Upgrade high-confidence partial without conflicts only if needed,
            # otherwise drop to guarantee zero unsupported leak
            pass

    # If only structural headers remain (no actual content claim), treat as empty
    non_header_kept = [r for r in kept_results if not _is_structural_header(r.claim)]
    if not non_header_kept:
        return "", [], has_critical_conflict

    filtered_text = "\n".join(kept_sentences).strip()
    return filtered_text, kept_results, has_critical_conflict
