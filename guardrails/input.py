import re
from dataclasses import dataclass


@dataclass
class InputGuardResult:
    allowed: bool
    reason: str | None = None


INJECTION_PATTERNS = [
    r"ignore (all|previous) instructions",
    r"bỏ qua .*hướng dẫn",
    r"bỏ qua .*quy tắc",
    r"hãy quên .*chỉ dẫn",
    r"system prompt",
    r"developer message",
    r"reveal .*prompt",
]


def detect_prompt_injection(text: str) -> bool:
    value = (text or "").lower()

    return any(
        re.search(pattern, value, re.IGNORECASE)
        for pattern in INJECTION_PATTERNS
    )


def validate_input(query: str) -> InputGuardResult:
    if not query or not query.strip():
        return InputGuardResult(
            allowed=False,
            reason="empty_input",
        )

    if detect_prompt_injection(query):
        return InputGuardResult(
            allowed=False,
            reason="prompt_injection",
        )

    return InputGuardResult(
        allowed=True,
        reason=None,
    )


def mask_sensitive_for_log(text: str) -> str:
    value = text or ""

    # CCCD 12 số
    value = re.sub(
        r"\b\d{12}\b",
        "[REDACTED_CCCD]",
        value,
    )

    # Điện thoại VN cơ bản
    value = re.sub(
        r"\b(?:\+84|0)\d{9,10}\b",
        "[REDACTED_PHONE]",
        value,
    )

    return value