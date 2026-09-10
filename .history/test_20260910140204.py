# from rag.rerank import rerank
# from rag.retrieval import retrieve
# from rag.evidence_builder import build_evidence_candidates

# results = retrieve(
#     "Tôi cần những giấy tờ gì để đăng ký khai sinh?",
#     context={}
# )

# ranked = rerank(results)

# candidates = build_evidence_candidates(ranked)

# for candidate in candidates:
#     print(candidate)


from rag.generator import generate_answer

answer = generate_answer(
    "Xin chào. Hãy trả lời bằng tiếng Việt: Bạn có thể giúp tôi không?"
)

print(answer)