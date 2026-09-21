from rag.evidence_builder import EvidenceCandidate


def _format_context(context: dict | None) -> str:
    """
    Format conversation context dictionary into readable text.
    """
    if not context:
        return "No conversation context was provided."

    if isinstance(context, dict):
        recent_messages = context.get("recent_messages")
        if recent_messages and isinstance(recent_messages, list):
            lines = [f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in recent_messages]
            return "\n".join(lines)
        
        structured_context = context.get("structured_context")
        if structured_context:
            return str(structured_context)

    return str(context)


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
    7. Nếu bằng chứng không đủ để trả lời câu hỏi, hãy trả lời chính xác:
    "Thông tin trong tài liệu được cung cấp chưa đủ để trả lời câu hỏi này."

    8. Ngữ cảnh hội thoại chỉ được sử dụng để hiểu ý định của người dùng, không được xem là bằng chứng pháp lý.

    9. Luôn trả lời bằng tiếng Việt và ngắn gọn, rõ ràng.

    10. Khi sử dụng thông tin từ một evidence candidate, phải trích dẫn candidate ID tương ứng** theo định dạng:
    [số thứ tự trích dẫn]. Title của evidence

    11. Nếu người dùng hỏi về các giấy tờ cần thiết, chỉ liệt kê những giấy tờ được nêu rõ trong bằng chứng.
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