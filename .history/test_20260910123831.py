from rag.retrieval import retrieve

query = "Thủ tục xác nhận tình trạng hôn nhân mất bao lâu?"

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
