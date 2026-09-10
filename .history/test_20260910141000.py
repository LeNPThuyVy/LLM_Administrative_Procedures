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

import sys
from rag.pipeline
sys.stdout.reconfigure(encoding='utf-8')

def fake_generator(prompt: str) -> str:
    return "Hồ sơ đăng ký khai sinh cần giấy chứng sinh."

response = answer_query(
    query="Tôi cần những giấy tờ gì để đăng ký khai sinh?",
    context=None,
    generator=fake_generator,
)

print(response)