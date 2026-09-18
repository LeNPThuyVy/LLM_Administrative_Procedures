from rag.pipeline import answer_query

context = {
    "recent_messages": [
        {
            "role": "user",
            "content": "Tôi đang hỏi về thủ tục hành chính tại Bình Dương."
        },
        {
            "role": "assistant",
            "content": "Bạn muốn hỏi thủ tục nào tại Bình Dương?"
        }
    ],
    "conversation_summary": "",
    "structured_context": {}
}

result = answer_query(
    "Vậy cần chuẩn bị những giấy tờ gì?",
    context=context
)

print("\n=== TEST 2 ===")
print(result)