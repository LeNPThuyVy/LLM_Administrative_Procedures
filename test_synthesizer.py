import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.append('t:\\OneDrive\\Backup\\My_Document\\Lexatek_Intern\\LLM_Legal\\LLM_Administrative_Procedures')

import my_config as cfg
from rag.retrieval import RetrievedChunk
from rag.synthesizer import synthesizer

query = "Mình muốn hỏi thủ tục"
history = {"recent_messages": []}

# fake procedure hints that might be returned by retriever
procedure_hint = [
    RetrievedChunk(
        document_id="doc1",
        chunk_id="doc1_general",
        content="thủ tục đăng kí kết hôn",
        retrieval_score=0.9,
        metadata={"title": "Đăng kí kết hôn"}
    )
]

def dummy_generator(prompt: str) -> str:
    return '{"resolved_query": "Mình muốn hỏi thủ tục đăng kí kết hôn", "original_query": "Mình muốn hỏi thủ tục", "needs_clarification": false, "clarification_question": null}'

res = synthesizer(query, history, procedure_hint, generator=dummy_generator, domain="administrative_procedures")
print(res)
