from rag.retrieval import retrieve

context = {
    "structured_context": {
        "procedure": "Đăng ký khai sinh",
        "location": "TP.HCM"
    },
    "recent_messages": [],
    "long_term_memory": []
}



results = retrieve(
    "Tôi cần những giấy tờ gì?",
    context
)

for result in results:
    print(result)