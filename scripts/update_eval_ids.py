import json
from pathlib import Path

p = Path('test/eval_cases.json')
content = p.read_text(encoding='utf-8')

replacements = {
    'PROC_008': 'PROC_020',
    'PROC_009': 'PROC_023',
    'PROC_010': 'PROC_016',
    'PROC_014': 'PROC_019',
    'PROC_015': 'PROC_011',
    'PROC_025': 'PROC_027',
    'PROC_028': 'PROC_032',
}

for k, v in replacements.items():
    content = content.replace(f'"expected_doc_id": "{k}"', f'"expected_doc_id": "{v}"')

p.write_text(content, encoding='utf-8')
print('Updated eval_cases.json with deduplicated IDs')
