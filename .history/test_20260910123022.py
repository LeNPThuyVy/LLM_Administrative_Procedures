from rag.retrieval import retrieve

query = "Tôi cần những giấy tờ gì để đăng ký khai sinh?"

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
