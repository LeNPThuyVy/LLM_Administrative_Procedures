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
    r"đóng vai\b",
    r"không bị giới hạn\b",
    r"lách luật\b",
    r"developer mode\b",
    r"\bDAN\b",
    r"in ra .*(\.env|api key|chuỗi kết nối|mật khẩu)",
    r"\b(api[-_ ]?key|connection[-_ ]?string|chuỗi kết nối|database_url)\b",
    r"\.env\b",
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

    # Email
    value = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "[REDACTED_EMAIL]",
        value,
    )

    # CMND 9 số
    value = re.sub(
        r"(?<!\d)\d{9}(?!\d)",
        "[REDACTED_CMND]",
        value,
    )

    return value