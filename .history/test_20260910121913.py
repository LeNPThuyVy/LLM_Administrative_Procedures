from rag.retrieval import retrieve

query = "Tôi cần những giấy tờ gì để đăng ký khai sinh?"

context = {
    "conversation_summary": {},
    "recent_messages": [],
    "structured_context": {
        "procedure": "Thủ tục đăng ký khai sinh",
        "location": "TP.HCM"
    },
    "long_term_memory": []
}

results = retrieve(
    "Tôi cần những giấy tờ gì?",
    context
)

for result in results:
    print(result)