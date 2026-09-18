from rag.pipeline import answer_query

result = answer_query(
    "Người dân cần chuẩn bị giấy tờ gì để thực hiện thủ tục?"
)

print("\n=== TEST 1 ===")
print(result)