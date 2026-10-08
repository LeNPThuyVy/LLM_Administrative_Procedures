import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.append('t:\\OneDrive\\Backup\\My_Document\\Lexatek_Intern\\LLM_Legal\\LLM_Administrative_Procedures')
from rag.synthesizer import _has_specific_procedure_keyword

print(_has_specific_procedure_keyword('Mình muốn hỏi thủ tục', domain='administrative_procedures'))
