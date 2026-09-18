from rag.evidence_builder import EvidenceCandidate
from rag.prompt_builder import build_prompt
from rag.remote_generator import generate_remote


evidence = EvidenceCandidate(
    candidate_id="EC_001",
    chunk_id="chunk_001",
    document_id="doc_001",
    content=(
        "Thủ tục cấp bản sao giấy tờ hộ tịch yêu cầu người dân chuẩn bị: "
        "Tờ khai yêu cầu cấp bản sao và căn cước công dân hoặc giấy tờ tùy thân hợp lệ."
    ),
    title="Thủ tục cấp bản sao giấy tờ hộ tịch",
    document_type="administrative_procedure",
    page=1,
    source_url=None,
    retrieval_score=0.95,
    rerank_score=0.95,
)


prompt = build_prompt(
    query="Người dân cần chuẩn bị những gì để thực hiện thủ tục này?",
    evidence_candidates=[evidence],
)


print("=== GENERATED PROMPT ===")
print(prompt)

print("\n=== REMOTE ANSWER ===")

answer = generate_remote(prompt)

print(answer)