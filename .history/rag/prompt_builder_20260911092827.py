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
        You are a Legal AI Assistant for administrative procedures.

        Your task is to answer the user's question using ONLY the information explicitly stated in the provided evidence.

        STRICT RULES:
        1. Use only facts explicitly stated in the evidence.
        2. Do not use your own knowledge.
        3. Do not invent or infer missing information.
        4. Do not add explanations that are not stated in the evidence.
        5. Do not add documents that are not listed in the evidence.
        6. Do not repeat documents or information.
        7. If the evidence is insufficient, say:
        "Thông tin trong tài liệu được cung cấp chưa đủ để trả lời câu hỏi này."
        8. Context is only for understanding the user's intent. It is NOT legal evidence.
        9. Answer concisely in Vietnamese.
        10. Cite the evidence candidate ID like [{evidence_candidates[0].candidate_id if evidence_candidates else 'EC_001'}] when stating information from that evidence.
        11. If the user asks for required documents, list ONLY the documents explicitly stated in the evidence.

        USER QUESTION:
        {query}

        CONVERSATION CONTEXT:
        {context_text}

        PROVIDED EVIDENCE:
        {evidence_text}


        Now answer the user's question based on the provided evidence.
        """.strip()

    return prompt