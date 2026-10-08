"""
Prompt Builder — constructs the final answer-generation prompt.

Uses:
- current user query
- conversation summary
- recent messages
- structured context
- long-term memory
- verified evidence

Also detects which administrative procedure field the user is asking
about and restricts the answer to the requested field(s).
"""

from rag.evidence_builder import EvidenceCandidate


# =========================================================
# FIELD DETECTION
# =========================================================

import re as _re

# =========================================================
# FIELD DETECTION PATTERNS
# GĐ1 mục 3: Dùng regex word-boundary, tránh match substring rộng.
# Thứ tự kiểm tra: method → docs → fee → time
# để "nộp hồ sơ ở đâu" ra method, không ra docs.
# =========================================================

# Regex patterns — dùng \b để tránh match giữa từ
_METHOD_REGEX = _re.compile(
    r"\b(hình\s+thức\s+nộp|nộp\s+online|nộp\s+trực\s+tuyến|"
    r"nộp\s+trực\s+tiếp|cách\s+nộp|nộp\s+ở\s+đâu|submission\s+method)\b",
    _re.IGNORECASE | _re.UNICODE,
)

# "hồ sơ" và "phí" đứng riêng bị bỏ (quá rộng).
# Chỉ giữ cụm từ cụ thể hơn.
_DOCS_REGEX = _re.compile(
    r"\b(giấy\s+tờ|thành\s+phần\s+hồ\s+sơ|cần\s+chuẩn\s+bị|"
    r"tài\s+liệu|giấy\s+chứng\s+minh|giấy\s+chứng\s+sinh|"
    r"giấy\s+khai|cần\s+gì|bao\s+gồm\s+những\s+gì|required)\b",
    _re.IGNORECASE | _re.UNICODE,
)

_FEE_REGEX = _re.compile(
    r"\b(lệ\s+phí|chi\s+phí|miễn\s+phí|bao\s+nhiêu\s+tiền|"
    r"fee|mất\s+bao\s+nhiêu)\b",
    _re.IGNORECASE | _re.UNICODE,
)

_TIME_REGEX = _re.compile(
    r"\b(thời\s+gian|bao\s+lâu|mấy\s+ngày|thời\s+hạn|"
    r"bao\s+nhiêu\s+ngày|processing\s+time)\b",
    _re.IGNORECASE | _re.UNICODE,
)

# Thứ tự kiểm tra: method trước docs
_ORDERED_FIELD_CHECKS = [
    ("method", _METHOD_REGEX),
    ("docs",   _DOCS_REGEX),
    ("fee",    _FEE_REGEX),
    ("time",   _TIME_REGEX),
]

_FIELD_LABELS = {
    "docs": "GIẤY TỜ / HỒ SƠ cần thiết",
    "fee": "LỆ PHÍ",
    "time": "THỜI GIAN GIẢI QUYẾT",
    "method": "HÌNH THỨC NỘP HỒ SƠ",
}

_FIELD_SECTION_NAMES = {
    "docs": "'Thành phần hồ sơ'",
    "fee": "'Lệ phí'",
    "time": "'Thời gian giải quyết'",
    "method": "'Hình thức nộp'",
}


# =========================================================
# FIELD RESTRICTION
# =========================================================

def _detect_field_types(
    query: str,
    context: dict | None = None
) -> list[str]:
    """
    Detect all procedure fields requested by the user.

    GĐ1 mục 3:
    - Dùng regex word-boundary thay vì simple substring.
    - Thứ tự kiểm tra: method → docs → fee → time
      để "nộp hồ sơ ở đâu" ra method, không ra docs.
    - Nếu không detect được field nào → trả [] (không thêm restriction).
    """

    text_parts = [query or ""]

    if isinstance(context, dict):
        structured_context = context.get("structured_context", {}) or {}
        intent = structured_context.get("intent")
        if intent:
            text_parts.append(str(intent))

    q = " ".join(text_parts)

    detected = []
    for key, pattern in _ORDERED_FIELD_CHECKS:
        if pattern.search(q):
            detected.append(key)

    return detected


def _build_field_restriction_rule(
    field_types: list[str]
) -> str:
    """
    Build a soft focus rule for detected fields.

    GĐ1 mục 3: Chỉ nói "tập trung vào...", không cấm đề cập
    phần khác nếu thực sự liên quan trực tiếp.
    Khi không có field nào → trả "" (không thêm rule).
    """

    if not field_types:
        return ""

    asked_labels = "; ".join(
        _FIELD_LABELS[key]
        for key in field_types
    )

    asked_sections = ", ".join(
        _FIELD_SECTION_NAMES[key]
        for key in field_types
    )

    return (
        f"Câu hỏi này tập trung vào: {asked_labels}. "
        f"Ưu tiên trả lời phần {asked_sections}. "
        "Bạn vẫn có thể đề cập thông tin khác nếu nó liên quan trực tiếp."
    )


# =========================================================
# TEXT HELPERS
# =========================================================

def _extract_text(
    val: object
) -> str:
    """
    Safely extract text from string,
    list, tuple or dictionary.
    """

    if isinstance(val, str):
        return val

    if isinstance(val, list):
        return " ".join(
            _extract_text(item)
            for item in val
            if item
        )

    if isinstance(val, tuple):
        return " ".join(
            _extract_text(item)
            for item in val
            if item
        )

    if isinstance(val, dict):

        if (
            "text" in val
            and isinstance(
                val["text"],
                str
            )
        ):
            return val["text"]

        if "content" in val:
            return _extract_text(
                val["content"]
            )

        return " ".join(
            _extract_text(value)
            for value in val.values()
            if value
        )

    return (
        str(val)
        if val is not None
        else ""
    )


def _format_mapping(
    data: dict | None
) -> str:
    """
    Format dictionary values in a readable way.
    Ignore empty values.
    """

    if not isinstance(data, dict):
        return ""

    lines = []

    for key, value in data.items():

        if value is None:
            continue

        if isinstance(value, str):
            value = value.strip()

            if not value:
                continue

        if isinstance(value, list):
            if not value:
                continue

            value = ", ".join(
                str(item)
                for item in value
            )

        lines.append(
            f"- {key}: {value}"
        )

    return "\n".join(lines)


# =========================================================
# CONTEXT FORMATTER
# =========================================================

def _format_context(
    context: dict | None
) -> str:
    """
    Format all Context Manager components:

    - conversation_summary
    - recent_messages
    - structured_context
    - long_term_memory
    """

    if (
        not isinstance(context, dict)
        or not context
    ):
        return (
            "Không có ngữ cảnh hội thoại trước đó."
        )

    parts = []

    # -----------------------------------------------------
    # CONVERSATION SUMMARY
    # -----------------------------------------------------

    conversation_summary = context.get(
        "conversation_summary",
        ""
    )

    if conversation_summary:

        parts.append(
            "TÓM TẮT HỘI THOẠI TRƯỚC:\n"
            + _extract_text(
                conversation_summary
            )
        )

    # -----------------------------------------------------
    # RECENT MESSAGES
    # -----------------------------------------------------

    recent_messages = context.get(
        "recent_messages",
        []
    )

    if (
        recent_messages
        and isinstance(
            recent_messages,
            list
        )
    ):

        lines = []

        for message in recent_messages:

            if isinstance(
                message,
                dict
            ):

                role = message.get(
                    "role",
                    "user"
                )

                content = _extract_text(
                    message.get(
                        "content",
                        ""
                    )
                )

                if content:
                    lines.append(
                        f"{role}: {content}"
                    )

            elif (
                isinstance(
                    message,
                    (list, tuple)
                )
                and len(message) == 2
            ):

                user_text = _extract_text(
                    message[0]
                )

                assistant_text = _extract_text(
                    message[1]
                )

                lines.append(
                    f"user: {user_text}"
                )

                lines.append(
                    f"assistant: "
                    f"{assistant_text}"
                )

        if lines:

            parts.append(
                "TIN NHẮN GẦN ĐÂY:\n"
                + "\n".join(lines)
            )

    # -----------------------------------------------------
    # STRUCTURED CONTEXT
    # -----------------------------------------------------

    structured_context = context.get(
        "structured_context",
        {}
    ) or {}

    formatted_structured = (
        _format_mapping(
            structured_context
        )
    )

    if formatted_structured:

        parts.append(
            "STRUCTURED CONTEXT "
            "(dùng để hiểu câu hỏi hiện tại):\n"
            + formatted_structured
        )

    # -----------------------------------------------------
    # LONG-TERM MEMORY
    # -----------------------------------------------------

    long_term_memory = context.get(
        "long_term_memory",
        {}
    ) or {}

    formatted_memory = (
        _format_mapping(
            long_term_memory
        )
    )

    if formatted_memory:

        parts.append(
            "LONG-TERM MEMORY "
            "(thông tin đã lưu trong phiên):\n"
            + formatted_memory
        )

    if not parts:
        return (
            "Không có ngữ cảnh hội thoại trước đó."
        )

    return "\n\n".join(parts)


# =========================================================
# PROMPT BUILDER
# =========================================================

def build_prompt(
    query: str,
    evidence_candidates: list[EvidenceCandidate],
    context: dict | None = None,
    domain: str | None = None
) -> str:
    """
    Build final generation prompt.

    Context is used only to understand:
    - current procedure
    - location
    - intent
    - multi-turn references

    Evidence remains the only factual/legal source
    used to produce the final answer.
    """
    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)
    assistant_role = runtime.assistant_role or "chuyên gia tư vấn"

    # =====================================================
    # EVIDENCE
    # =====================================================

    evidence_sections: list[str] = []

    for evidence in evidence_candidates:
        cid = evidence.chunk_id or ""
        category_label = ""
        if cid.endswith("_docs"):
            category_label = " [MỤC THÀNH PHẦN HỒ SƠ / GIẤY TỜ]"
        elif cid.endswith("_fee"):
            category_label = " [MỤC LỆ PHÍ / CHI PHÍ]"
        elif cid.endswith("_time"):
            category_label = " [MỤC THỜI GIAN GIẢI QUYẾT]"
        elif cid.endswith("_method"):
            category_label = " [MỤC HÌNH THỨC NỘP HỒ SƠ / ĐỊA ĐIỂM]"
        elif cid.endswith("_general"):
            category_label = " [MỤC THÔNG TIN TỔNG QUAN THỦ TỤC]"

        section = (
            f"[Evidence {evidence.candidate_id}]{category_label}\n"
            f"document_id: {evidence.document_id}\n"
            f"chunk_id: {evidence.chunk_id}\n"
            f"title: {evidence.title}\n"
            f"content:\n"
            f"{evidence.content}"
        )

        evidence_sections.append(section)

    evidence_text = "\n\n".join(evidence_sections)

    if not evidence_text:
        evidence_text = "No evidence was provided."

    # =====================================================
    # CONTEXT
    # =====================================================

    context_text = _format_context(context)

    # =====================================================
    # FIELD RESTRICTION
    # =====================================================

    field_types = _detect_field_types(
        query=query,
        context=context
    )

    restriction_text = _build_field_restriction_rule(field_types)

    # =====================================================
    # FINAL PROMPT — GĐ1 mục 2
    # Tách system/user, 6 quy tắc tích cực, few-shot example.
    # Citation chỉ ở cuối đoạn, không chèn giữa câu.
    # =====================================================

    field_focus = (
        f"\n{restriction_text}" if restriction_text else ""
    )

    system_block = f"""Bạn là {assistant_role} thân thiện và chính xác.

QUY TẮC:
1. Diễn đạt rõ ràng dễ hiểu, QUAN TRỌNG LÀ PHẢI BÁM SÁT BẰNG CHỨNG ĐƯỢC CUNG CẤP, KHÔNG ĐƯA Ý KIẾN HAY KIẾN THỨC RIÊNG VÀO CÂU TRẢ LỜI  .
2. Giữ nguyên chính xác: số tiền, thời hạn, tên giấy tờ, tên cơ quan.
3. Nếu người dùng hỏi nhiều ý (multi-intent: vừa hỏi giấy tờ, vừa hỏi thời gian hay lệ phí), hãy trả lời đầy đủ từng ý theo cấu trúc rõ ràng.
4. Ý nào bằng chứng không đề cập → nói rõ "chưa có thông tin về phần này". KHÔNG tự suy đoán.
5. Cuối câu trả lời, gợi ý một điều người dùng có thể hỏi tiếp.
6. Trả lời bằng tiếng Việt, rõ ràng, tự nhiên.
7. Chỉ dùng thông tin từ phần BẰNG CHỨNG — không dùng kiến thức riêng.{field_focus}
8. Một câu trả lời cần chứa tối thiểu thông tin về tên thủ tục (được in đậm và tách ra dòng riêng để người dùng đọc vào là biết tên thủ tục). Các thông tin còn lại phải được viết rõ ràng, có bullet cho từng thông tin, không viết chùm chùm.
9. Người dùng hỏi gì thì trả lời đó không trả lời dư: ví dụ người dùng hỏi lệ phí thủ tục đăng kí kết hôn thì chỉ trả thủ tục đăng kí kết hôn.
10. Sau khi đưa ra câu trả lời về thủ tục cho người dùng thì hãy kết câu bằng: "Bạn muốn hỏi thêm về thông tin thủ tục nào không?"

ĐÂY LÀ MẪU THỦ TỤC ĐỂ THAM KHẢO (KHÔNG COPY HAY BÊ Y NGUYÊN VÀO CÂU TRẢ LỜI, CHỈ TRẢ LỜI THEO FORMAT NÀY)
Tên thủ tục: [Tên thủ tục]
 - Hình thức nộp: [Thông tin về hình thức nộp]
 - Thành phần hồ sơ: [Thông tin về thành phần hồ sơ]
 - Lệ phí: [Thông tin về lệ phí]
 - Thời gian giải quyết: [Thông tin về thời gian]
 - Địa chỉ cơ quan tiếp nhận hồ sơ: [Thông tin về địa chỉ cơ quan tiếp nhận hồ sơ]


"""

    user_block = f"""NGỮ CẢNH HỘI THOẠI:
{context_text}

BẰNG CHỨNG:
{evidence_text}

CÂU HỎI: {query}

Hãy trả lời dựa trên bằng chứng trên, diễn đạt tự nhiên, kèm citation [xxx] ở cuối đoạn dùng thông tin đó."""

    # Kết hợp thành một prompt duy nhất
    prompt = f"{system_block}\n\n{user_block}"

    return prompt