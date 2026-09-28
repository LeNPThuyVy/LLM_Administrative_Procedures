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

_DOCS_PATTERNS = (
    "giấy tờ",
    "hồ sơ",
    "thành phần hồ sơ",
    "cần chuẩn bị",
    "tài liệu",
    "giấy chứng minh",
    "giấy chứng sinh",
    "giấy khai",
    "cần gì",
    "bao gồm những gì",
    "required",
)

_FEE_PATTERNS = (
    "lệ phí",
    "phí",
    "chi phí",
    "miễn phí",
    "bao nhiêu tiền",
    "fee",
    "mất bao nhiêu",
)

_TIME_PATTERNS = (
    "thời gian",
    "bao lâu",
    "mấy ngày",
    "mấy ngày làm việc",
    "thời hạn",
    "bao nhiêu ngày",
    "processing time",
)

_METHOD_PATTERNS = (
    "hình thức nộp",
    "nộp online",
    "nộp trực tuyến",
    "nộp trực tiếp",
    "cách nộp",
    "nộp ở đâu",
    "submission method",
)


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

_FIELD_PATTERNS = {
    "docs": _DOCS_PATTERNS,
    "fee": _FEE_PATTERNS,
    "time": _TIME_PATTERNS,
    "method": _METHOD_PATTERNS,
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

    Ngoài query hiện tại, có thể dùng intent trong
    structured_context để hiểu câu hỏi multi-turn.
    """

    text_parts = [
        query or ""
    ]

    if isinstance(context, dict):

        structured_context = context.get(
            "structured_context",
            {}
        ) or {}

        intent = structured_context.get(
            "intent"
        )

        if intent:
            text_parts.append(
                str(intent)
            )

    q = " ".join(
        text_parts
    ).lower()

    detected = []

    for key in (
        "docs",
        "fee",
        "time",
        "method"
    ):
        if any(
            pattern in q
            for pattern in _FIELD_PATTERNS[key]
        ):
            detected.append(key)

    return detected


def _build_field_restriction_rule(
    field_types: list[str]
) -> str:
    """
    Restrict the answer to only the fields
    actually asked by the user.
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

    excluded = [
        key
        for key in _FIELD_LABELS
        if key not in field_types
    ]

    exclusion_text = ""

    if excluded:

        excluded_labels = ", ".join(
            _FIELD_LABELS[key]
            for key in excluded
        )

        exclusion_text = (
            " Không đề cập các nội dung khác "
            f"không được hỏi ({excluded_labels})."
        )

    return (
        f"16. Câu hỏi này hỏi về: {asked_labels}. "
        f"Chỉ trả lời đúng (các) phần "
        f"{asked_sections} từ bằng chứng."
        f"{exclusion_text}"
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
    context: dict | None = None
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

    # =====================================================
    # EVIDENCE
    # =====================================================

    evidence_sections: list[str] = []

    for evidence in evidence_candidates:

        section = (
            f"[Evidence {evidence.candidate_id}]\n"
            f"document_id: {evidence.document_id}\n"
            f"chunk_id: {evidence.chunk_id}\n"
            f"title: {evidence.title}\n"
            f"content:\n"
            f"{evidence.content}"
        )

        evidence_sections.append(
            section
        )

    evidence_text = "\n\n".join(
        evidence_sections
    )

    if not evidence_text:
        evidence_text = (
            "No evidence was provided."
        )

    # =====================================================
    # CONTEXT
    # =====================================================

    context_text = _format_context(
        context
    )

    # =====================================================
    # FIELD RESTRICTION
    # =====================================================

    field_types = _detect_field_types(
        query=query,
        context=context
    )

    restriction_text = (
        _build_field_restriction_rule(
            field_types
        )
    )

    field_restriction_rule = (
        "\n    " + restriction_text
        if restriction_text
        else ""
    )

    # =====================================================
    # FINAL PROMPT
    # =====================================================

    prompt = f"""
    Bạn là Trợ lý AI hỗ trợ các thủ tục hành chính.

    Nhiệm vụ của bạn là trả lời câu hỏi của người dùng
    bằng cách chỉ sử dụng thông tin được nêu rõ trong
    các bằng chứng được cung cấp.

    QUY TẮC BẮT BUỘC

    1. Chỉ sử dụng thông tin có trong bằng chứng.
    2. Không sử dụng kiến thức riêng của bạn hoặc bất kỳ thông tin nào không được cung cấp trong bằng chứng.
    3. Không tự suy luận, phỏng đoán hoặc bổ sung thông tin còn thiếu.
    4. Không đưa ra giải thích hoặc kết luận nếu nội dung đó không được nêu rõ trong bằng chứng.
    5. Không thêm bất kỳ giấy tờ nào ngoài những giấy tờ được liệt kê rõ ràng trong bằng chứng.
    6. Không lặp lại giấy tờ hoặc thông tin.
    7. Nếu bằng chứng có chứa thông tin trực tiếp trả lời câu hỏi, hãy trả lời đầy đủ các thông tin đó. Không yêu cầu bằng chứng phải mô tả
    toàn bộ thủ tục mới được trả lời.


    Chỉ trả lời:

    "Thông tin trong bằng chứng chưa đủ để trả lời câu hỏi này."

    khi bằng chứng hoàn toàn không chứa thông tin liên quan
    trực tiếp đến câu hỏi.

    8. Ngữ cảnh hội thoại, structured context và long-term
    memory chỉ được sử dụng để hiểu người dùng đang hỏi
    thủ tục nào, ở đâu và đang hỏi tiếp vấn đề gì.

    Không xem chúng là bằng chứng pháp lý hoặc nguồn để
    tạo ra thông tin hành chính.

    9. Luôn trả lời bằng tiếng Việt, ngắn gọn và rõ ràng.

    10. Khi sử dụng thông tin từ một evidence candidate,
    phải trích dẫn candidate ID tương ứng theo định dạng:

    [EC_XXX]. Title của evidence candidate

    Chỉ dùng đúng candidate ID đã được liệt kê trong phần
    BẰNG CHỨNG ĐƯỢC CUNG CẤP.

    11. Nếu người dùng hỏi về giấy tờ cần thiết và bằng
    chứng có nêu tên một hoặc nhiều giấy tờ, hãy liệt kê
    chính xác các giấy tờ đó.

    Không được từ chối trả lời chỉ vì bằng chứng có thể
    chưa liệt kê toàn bộ hồ sơ.

    12. Nếu có nhiều evidence candidate chứa cùng một
    thông tin, không lặp lại thông tin đó và chỉ cần
    trích dẫn evidence phù hợp.

    13. Không được tạo hoặc thay đổi candidate ID.
    Chỉ sử dụng candidate ID đã được cung cấp.

    14. Nếu câu hỏi chứa nhiều ý, chỉ trả lời những ý
    có đủ bằng chứng.

    Với những ý không có đủ bằng chứng, sử dụng câu trả
    lời mặc định ở Quy tắc 7.

    15. Không đề cập đến quá trình suy luận, hệ thống RAG,
    evidence, prompt, structured context, long-term memory
    hoặc các quy tắc nội bộ trong câu trả lời cho người dùng.
    {field_restriction_rule}

    CÂU HỎI CỦA NGƯỜI DÙNG

    {query}

    NGỮ CẢNH HỘI THOẠI

    {context_text}

    BẰNG CHỨNG ĐƯỢC CUNG CẤP

    {evidence_text}

    Hãy trả lời câu hỏi của người dùng dựa chỉ trên các
    bằng chứng được cung cấp và tuân thủ nghiêm ngặt
    tất cả các quy tắc trên.
    """.strip()

    return prompt