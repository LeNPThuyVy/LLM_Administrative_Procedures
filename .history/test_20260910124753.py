from rag.rerank import rerank
from rag.retrieval im

results = retrieve(
    "Tôi cần những giấy tờ gì để đăng ký khai sinh?",
    context={}
)

ranked = rerank(results)

candidates = build_evidence_candidates(ranked)

for candidate in candidates:
    print(candidate)