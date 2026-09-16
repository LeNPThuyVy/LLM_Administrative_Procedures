async def get_context(session_id: str, query: str):
    return {
        "session_id": session_id,
        "conversation_summary": "Đây là context mock.",
        "recent_messages": [],
        "structured_context": {},
        "long_term_memory": []
    }