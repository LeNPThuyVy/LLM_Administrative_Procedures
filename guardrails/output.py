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


def sanitize_output(text: str) -> str:
    value = text or ""

    value = re.sub(
        r"\b\d{12}\b",
        "[REDACTED_CCCD]",
        value,
    )

    value = re.sub(
        r"\b(?:\+84|0)\d{9,10}\b",
        "[REDACTED_PHONE]",
        value,
    )

    return value


def apply_output_guard(
    answer: str,
    mode: str,
    disclaimer: str = "",
) -> str:
    result = sanitize_output(answer)

    if mode == "strict" and disclaimer:
        if disclaimer not in result:
            result = f"{result}\n\n{disclaimer}"

    return result