import json, sys
sys.stdout.reconfigure(encoding='utf-8')
data = json.load(open('data/procedures.json', encoding='utf-8'))
pairs = [
    ('PROC_008','PROC_020'),('PROC_010','PROC_016'),
    ('PROC_011','PROC_015'),('PROC_014','PROC_019'),
    ('PROC_009','PROC_023'),('PROC_028','PROC_032'),
    ('PROC_025','PROC_027')
]
doc_map = {p['document_id']: p for p in data}
for a, b in pairs:
    pa = doc_map.get(a, {})
    pb = doc_map.get(b, {})
    la = len(str(pa.get('content',''))+str(pa.get('required_documents','')))
    lb = len(str(pb.get('content',''))+str(pb.get('required_documents','')))
    keep = a if la >= lb else b
    ta = pa.get('title','')[:45]
    tb = pb.get('title','')[:45]
    print(f"{a}(len={la}) vs {b}(len={lb}) -> KEEP={keep}")
    print(f"  A: {ta}")
    print(f"  B: {tb}")
    print()
