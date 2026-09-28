"""
eval_fast.py — Chạy eval nhanh cho Retrieval, Field Detection và Multi-turn.
"""

import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from rag.pipeline import answer_query
from rag.retrieval import retrieve_two_step
from rag.prompt_builder import _detect_field_types
from rag.synthesizer import synthesizer
from rag.procedure_reader import procedure_reader
from rag.history_reader import history_reader

def mock_gen(prompt):
    return "Thủ tục hành chính được thực hiện theo quy định. [EC_001]"

cases = json.loads(Path(__file__).parent.joinpath("eval_cases.json").read_text(encoding="utf-8"))
single_cases = [c for c in cases if c["type"] == "single"]
multi_cases = [c for c in cases if c["type"] == "multi_turn"]

doc_hits = 0
field_matches = 0
total_single = len(single_cases)

print("=" * 60)
print("SINGLE-TURN EVALUATION (Retrieval & Field Detection)")
print("=" * 60)
for c in single_cases:
    q = c["query"]
    exp_doc = c.get("expected_doc_id")
    exp_field = c.get("expected_field")
    
    # Field detection
    det_fields = _detect_field_types(q)
    det_field = det_fields[0] if det_fields else None
    
    # Two-step Retrieval
    retrieved = retrieve_two_step(query=q, top_k=1)
    got_doc = retrieved[0].document_id if retrieved else None
    score = retrieved[0].retrieval_score if retrieved else 0.0
    
    hit = (got_doc == exp_doc) if exp_doc else (got_doc is None or score < 0.5)
    f_match = (det_field == exp_field) if exp_field else True
    
    if hit: doc_hits += 1
    if f_match: field_matches += 1
    
    status = "✓" if (hit and f_match) else "✗"
    print(f"[{status}] {c['id']} | Doc: exp={exp_doc} got={got_doc} ({'HIT' if hit else 'MISS'}) | Field: exp={exp_field} got={det_field} score={score:.3f}")

print(f"\nDoc Hit@1:     {doc_hits}/{total_single} = {doc_hits/total_single*100:.1f}%")
print(f"Field Match:   {field_matches}/{total_single} = {field_matches/total_single*100:.1f}%")

print("\n" + "=" * 60)
print("MULTI-TURN EVALUATION (Follow-up Resolution)")
print("=" * 60)
mt_pass = 0
for m in multi_cases:
    context = {}
    passed = True
    print(f"\n[{m['id']}] {m['description']}")
    for i, turn in enumerate(m["turns"]):
        q = turn["query"]
        exp_doc = turn.get("expected_doc_id")
        
        # Call answer_query with mock generator for fast test
        resp = answer_query(query=q, context=context, generator=mock_gen, synthesizer_generator=mock_gen)
        
        # Check retrieval via two-step
        proc_hint = procedure_reader(query=q, context=context, top_k=2)
        history = history_reader(context)
        cons = synthesizer(query=q, history=history, procedure_hint=proc_hint, generator=mock_gen)
        
        retrieved = retrieve_two_step(query=cons.resolved_query, context=context, top_k=1)
        got_doc = retrieved[0].document_id if retrieved else None
        
        turn_ok = (got_doc == exp_doc)
        if not turn_ok: passed = False
        print(f"  Turn {i+1}: '{q}' -> resolved: '{cons.resolved_query}' | exp={exp_doc} got={got_doc} {'✓' if turn_ok else '✗'}")
        
        if resp and resp.answer:
            msgs = context.get("recent_messages", [])
            msgs.append({"role": "user", "content": q})
            msgs.append({"role": "assistant", "content": resp.answer})
            context["recent_messages"] = msgs
            
    if passed: mt_pass += 1

print(f"\nMulti-turn Pass: {mt_pass}/{len(multi_cases)} = {mt_pass/len(multi_cases)*100:.1f}%")
