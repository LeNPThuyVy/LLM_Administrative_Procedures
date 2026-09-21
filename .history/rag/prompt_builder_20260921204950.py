"""
Prompt Builder — constructs the final answer-generation prompt.

Issue #5 fix: detect which field type the user is asking about
(required_documents / fee / processing_time / submission_method)
and add a field-restriction rule so the LLM only outputs the
relevant section, not every field in the evidence chunk.
"""

from rag.evidence_builder import EvidenceCandidate


_DOCS_PATTERNS = (
    "giấy tờ", "hồ sơ", "thành phần hồ sơ", "cần chuẩn bị",
    "tài liệu", "giấy chứng minh", "giấy chứng sinh", "giấy khai",
    "cần gì", "bao gồm những gì", "required",
)

_FEE_PATTERNS = (
    "lệ phí", "phí", "chi phí", "miễn phí", "bao nhiêu tiền",
    "fee", "mất bao nhiêu",
)

_TIME_PATTERNS = (
    "thời gian", "bao lâu", "mấy ngày", "mấy ngày làm việc",
    "thời hạn", "bao nhiêu ngày", "processing time",
)

_METHOD_PATTERNS = (
    "hình thức nộp", "nộp online", "nộp trực tuyến",
    "nộp trực tiếp", "cách nộp", "nộp ở đâu",
    "submission method",
)


def _detect_field_type(query: str) -> str | None:
    """
    Detect which procedure field the user is primarily asking about.

    Returns one of: 'docs', 'fee', 'time', 'method', or None.
    None means the query is general — no field restriction applied.
    """
    q = query.lower()

    if any(p in q for p in _FEE_PATTERNS):
        return "fee"

    if any(p in q for p in _TIME_PATTERNS):
        return "time"

    if any(p in q for p in _METHOD_PATTERNS):
        return "method"

    if any(p in q for p in _DOCS_PATTERNS):
        return "docs"

    return None


_FIELD_RESTRICTION_RULES = {
    "docs": (
        "16. Câu hỏi này hỏi về GIẤY TỜ / HỒ SƠ cần thiết. "
        "Chỉ liệt kê phần 'Thành phần hồ sơ' từ bằng chứng. "
        "Không đề cập lệ phí, thời gian giải quyết, hay hình thức nộp."
    ),
    "fee": (
        "16. Câu hỏi này hỏi về LỆ PHÍ. "
        "Chỉ trả lời phần 'Lệ phí' từ bằng chứng. "
        "Không đề cập giấy tờ, thời gian giải quyết, hay hình thức nộp."
    ),
    "time": (
        "16. Câu hỏi này hỏi về THỜI GIAN GIẢI QUYẾT. "
        "Chỉ trả lời phần 'Thời gian giải quyết' từ bằng chứng. "
        "Không đề cập giấy tờ, lệ phí, hay hình thức nộp."
    ),
    "method": (
        "16. Câu hỏi này hỏi về HÌNH THỨC NỘP HỒ SƠ. "
        "Chỉ trả lời phần 'Hình thức nộp' từ bằng chứng. "
        "Không đề cập giấy tờ, lệ phí, hay thời gian giải quyết."
    ),
}


def _extract_text(val: object) -> str:
    """Safely extract string text from string, list, or dict message content."""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return " ".join(_extract_text(item) for item in val if item)
    if isinstance(val, dict):
        if "text" in val and isinstance(val["text"], str):
            return val["text"]
        if "content" in val:
            return _extract_text(val["content"])
        return " ".join(_extract_text(v) for v in val.values() if v)
    return str(val) if val is not None else ""


def _format_context(context: dict | None) -> str:
    """
    Format conversation context dictionary into readable text.
    """
    if not isinstance(context, dict) or not context:
        return "No conversation context was provided."

    parts = []

    recent_messages = context.get("recent_messages")
    if recent_messages and isinstance(recent_messages, list):
        lines = []
        for m in recent_messages:
            if isinstance(m, dict):
                role = m.get("role", "user")
                content = _extract_text(m.get("content", ""))
                lines.append(f"{role}: {content}")
            elif isinstance(m, (list, tuple)) and len(m) == 2:
                lines.append(f"user: {_extract_text(m[0])}\nassistant: {_extract_text(m[1])}")
        if lines:
            parts.append("\n".join(lines))

    structured_context = context.get("structured_context")
    if structured_context:
        parts.append(f"Thông tin đã biết: {structured_context}")

    return "\n".join(parts) if parts else "No conversation context was provided."


def build_prompt(query: str, evidence_candidates: list[EvidenceCandidate], context: dict | None = None) -> str:
    """
    Build a prompt for the LLM using query, context, and evidence.

    Issue #5 fix: if the query is specifically about one field
    (documents / fee / time / method), append a field-restriction
    rule so the model doesn't dump ALL fields from the evidence chunk.
    """

    evidence_sections: list[str] = []

    for evidence in evidence_candidates:
        section = (
            f"[Evidence {evidence.candidate_id}]\n"
            f"document_id: {evidence.document_id}\n"
            f"chunk_id: {evidence.chunk_id}\n"
            f"title: {evidence.title}\n"
            f"content:\n{evidence.content}"
        )

        evidence_sections.append(section)

    evidence_text = "\n\n".join(evidence_sections)

    if not evidence_text:
        evidence_text = "No evidence was provided."

    context_text = _format_context(context)

    # Issue #5 — build optional field-restriction rule
    field_type = _detect_field_type(query)
    field_restriction_rule = (
        "\n    " + _FIELD_RESTRICTION_RULES[field_type]
        if field_type
        else ""
    )

    prompt = f"""
    Bạn là Trợ lý AI hỗ trợ các thủ tục hành chính.

    Nhiệm vụ của bạn là trả lời câu hỏi của người dùng bằng cách chỉ sử dụng thông tin được nêu rõ trong các bằng chứng được cung cấp.

    QUY TẮC BẮT BUỘC

    1. Chỉ sử dụng thông tin có trong bằng chứng.
    2. Không sử dụng kiến thức riêng của bạn hoặc bất kỳ thông tin nào không được cung cấp trong bằng chứng.
    3. Không tự suy luận, phỏng đoán hoặc bổ sung thông tin còn thiếu.
    4. Không đưa ra giải thích hoặc kết luận nếu nội dung đó không được nêu rõ trong bằng chứng.
    5. Không thêm bất kỳ giấy tờ nào ngoài những giấy tờ được liệt kê rõ ràng trong bằng chứng.
    6. Không lặp lại giấy tờ hoặc thông tin.
    7. Nếu bằng chứng có chứa ít nhất 2 thông tin trực tiếp trả lời câu hỏi, hãy trả lời bằng những thông tin đó. Không yêu cầu bằng chứng phải mô tả
    toàn bộ thủ tục mới được trả lời.

    Chỉ trả lời:
    "Thông tin trong chưa đủ để trả lời câu hỏi này."
    khi bằng chứng hoàn toàn không chứa thông tin liên quan trực tiếp đến câu hỏi.

    8. Ngữ cảnh hội thoại chỉ được sử dụng để hiểu ý định của người dùng, không được xem là bằng chứng pháp lý.

    9. Luôn trả lời bằng tiếng Việt và ngắn gọn, rõ ràng.

    10. Khi sử dụng thông tin từ một evidence candidate, phải trích dẫn candidate ID tương ứng theo định dạng:
    [EC_XXX]. Title của evidence candidate
    Chỉ dùng đúng candidate ID đã được liệt kê trong phần BẰNG CHỨNG ĐƯỢC CUNG CẤP.

    11. Nếu người dùng hỏi về giấy tờ cần thiết và bằng chứng có nêu tên một hoặc nhiều giấy tờ, hãy liệt kê chính xác các giấy tờ đó.
    Không được từ chối trả lời chỉ vì bằng chứng có thể chưa liệt kê toàn bộ hồ sơ.
    12. Nếu có nhiều evidence candidate chứa cùng một thông tin, không lặp lại thông tin đó và chỉ cần trích dẫn evidence phù hợp.
    13. Không được tạo hoặc thay đổi candidate ID. Chỉ sử dụng candidate ID đã được cung cấp.
    14. Nếu câu hỏi chứa nhiều ý, chỉ trả lời những ý có đủ bằng chứng. Với những ý không có đủ bằng chứng, sử dụng câu trả lời mặc định ở Quy tắc 7.
    15. Không đề cập đến quá trình suy luận, hệ thống RAG, evidence, prompt hoặc các quy tắc nội bộ trong câu trả lời cho người dùng.{field_restriction_rule}

    CÂU HỎI CỦA NGƯỜI DÙNG
    {query}

    NGỮ CẢNH HỘI THOẠI
    {context_text}

    BẰNG CHỨNG ĐƯỢC CUNG CẤP
    {evidence_text}

    Hãy trả lời câu hỏi của người dùng dựa chỉ trên các bằng chứng được cung cấp, tuân thủ nghiêm ngặt tất cả các quy tắc trên.
    """.strip()

    return prompt