import sys
import asyncio
sys.stdout.reconfigure(encoding='utf-8')
sys.path.append('t:\\OneDrive\\Backup\\My_Document\\Lexatek_Intern\\LLM_Legal\\LLM_Administrative_Procedures')

from rag.procedure_reader import procedure_reader

chunks = procedure_reader("Mình muốn hỏi thủ tục", context=None)
print("Procedure hint chunks:")
for c in chunks:
    print(c.metadata.get("title", ""), c.retrieval_score)
