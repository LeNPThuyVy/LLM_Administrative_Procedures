from rag.prompt_builder import build_prompt
from rag.remote_generator import generate_remote

prompt = build_prompt(
    query="Người dân cần chuẩn bị những gì để thực hiện thủ tục này?",
    evidence_candidates=[
        # Tạm thời dùng object EvidenceCandidate thật của project
    ],
)

print(prompt)