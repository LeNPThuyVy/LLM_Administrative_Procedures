from rag.evidence_builder import EvidenceCandidate


def _format_context(context: dict | None) -> str:
    """
    Format conversation context dictionary into readable text.
    """
    if not isinstance(context, dict) or not context:
        return "No conversation context was provided."

    parts = []

    recent_messages = context.get("recent_messages")
    if recent_messages and isinstance(recent_messages, list):
        lines = [f"{m.get('role', 'user')}: {m.get('content', '')}" for m in recent_messages]
        parts.append("\n".join(lines))

    structured_context = context.get("structured_context")
    if structured_context:
        parts.append(f"Thông tin đã biết: {structured_context}")

    return "\n".join(parts) if parts else "No conversation context was provided."


def build_prompt(query: str, evidence_candidates: list[EvidenceCandidate], context: dict | None = None) -> str:
    """
    Build a prompt for the LLM using query, context, and evidence.

    Context is used only to understand conversation context.
    Evidence is the only source of legal/procedural information.
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
    7. Nếu bằng chứng có chứa ít nhất một thông tin trực tiếp trả lời câu hỏi, hãy trả lời bằng những thông tin đó. Không yêu cầu bằng chứng phải mô tả
    toàn bộ thủ tục mới được trả lời.
    8. Câu hỏi của người dùng

    Chỉ trả lời:
    "Thông tin trong tài liệu được cung cấp chưa đủ để trả lời câu hỏi này."
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
    15. Không đề cập đến quá trình suy luận, hệ thống RAG, evidence, prompt hoặc các quy tắc nội bộ trong câu trả lời cho người dùng.

    CÂU HỎI CỦA NGƯỜI DÙNG
    {query}

    NGỮ CẢNH HỘI THOẠI
    {context_text}

    BẰNG CHỨNG ĐƯỢC CUNG CẤP
    {evidence_text}

    Hãy trả lời câu hỏi của người dùng dựa chỉ trên các bằng chứng được cung cấp, tuân thủ nghiêm ngặt tất cả các quy tắc trên.
    """.strip()

    return prompt