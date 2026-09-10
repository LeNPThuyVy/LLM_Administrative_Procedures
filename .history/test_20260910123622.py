from rag.retrieval import retrieve

query = "Đăng ký kết hôn cần chuẩn bị những giấy tờ gì?"

context = {
    "conversation_summary": {},
    "recent_messages": [],
    "structured_context": {},
    "long_term_memory": []
}

results = retrieve(query, context)

for result in results:
    print(
        result.document_id,
        result.retrieval_score,
        result.metadata["title"]
    )
