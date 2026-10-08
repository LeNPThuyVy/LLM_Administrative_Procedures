import re


def contains_sensitive_data(text: str) -> bool:
    value = text or ""

    patterns = [
        r"\b\d{12}\b",
        r"\b(?:\+84|0)\d{9,10}\b",
    ]

    return any(
        re.search(pattern, value)
        for pattern in patterns
    )


def sanitize_output(text: str, allowed_text: str = "") -> str:
    value = text or ""

    def repl_cccd(match):
        m = match.group(0)
        if allowed_text and m in allowed_text:
            return m
        return "[REDACTED_CCCD]"

    value = re.sub(
        r"\b\d{12}\b",
        repl_cccd,
        value,
    )

    def repl_phone(match):
        m = match.group(0)
        if allowed_text and m in allowed_text:
            return m
        return "[REDACTED_PHONE]"

    value = re.sub(
        r"\b(?:\+84|0)(?:3|5|7|8|9)\d{8}\b",
        repl_phone,
        value,
    )

    return value


def apply_output_guard(
    answer: str,
    mode: str,
    disclaimer: str = "",
    allowed_text: str = ""
) -> str:
    result = sanitize_output(answer, allowed_text)

    if mode == "strict" and disclaimer:
        if disclaimer not in result:
            result = f"{result}\n\n{disclaimer}"

    return result