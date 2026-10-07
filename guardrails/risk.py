import re
from dataclasses import dataclass


@dataclass
class RiskResult:
    level: str
    force_strict: bool
    reasons: list[str]


HIGH_RISK_PATTERNS = {
    "medical": [
        r"\bthuốc\b",
        r"\bliều\b",
        r"\buống thuốc\b",
        r"\bđiều trị\b",
        r"\bchẩn đoán\b",
        r"\bbệnh\b",
        r"\bsức khỏe\b",
    ],
    "legal": [
        r"\bluật\b",
        r"\bpháp luật\b",
        r"\bnghị định\b",
        r"\bthông tư\b",
        r"\bquy định\b",
        r"\bxử phạt\b",
        r"\bkhởi kiện\b",
    ],
    "immigration": [
        r"\bvisa\b",
        r"\bhộ chiếu\b",
        r"\bxuất cảnh\b",
        r"\bnhập cảnh\b",
        r"\bcư trú\b",
        r"\bthị thực\b",
    ],
}


MEDIUM_RISK_PATTERNS = {
    "finance": [
        r"\bvay\b",
        r"\blãi suất\b",
        r"\bngân hàng\b",
        r"\bđầu tư\b",
        r"\bthuế\b",
    ],
}


def classify_risk(query: str) -> RiskResult:
    text = (query or "").lower().strip()

    high_reasons = []

    for category, patterns in HIGH_RISK_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                high_reasons.append(category)
                break

    if high_reasons:
        return RiskResult(
            level="high",
            force_strict=True,
            reasons=high_reasons,
        )

    medium_reasons = []

    for category, patterns in MEDIUM_RISK_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                medium_reasons.append(category)
                break

    if medium_reasons:
        return RiskResult(
            level="medium",
            force_strict=False,
            reasons=medium_reasons,
        )

    return RiskResult(
        level="low",
        force_strict=False,
        reasons=[],
    )


def resolve_mode(
    configured_mode: str,
    risk: RiskResult,
) -> str:
    mode = (configured_mode or "strict").lower()

    # Strict tuyệt đối không được hạ xuống friendly.
    if mode == "strict":
        return "strict"

    # Friendly chỉ bị nâng lên strict khi classifier xác định high-risk.
    if risk.force_strict:
        return "strict"

    return "friendly"