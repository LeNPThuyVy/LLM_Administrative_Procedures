"""
eval_ai.py — Bộ đánh giá tự động cho RAG pipeline.

Chỉ số:
- doc_hit_at_1: top-1 retrieved chunk có đúng document_id không
- field_match: field type detect có đúng expected_field không
- multi_turn_pass: tất cả turns trong kịch bản multi-turn đều pass
- fallback_rate: tỉ lệ dùng fallback text
- avg_latency_ms: độ trễ trung bình

In kèm resolved_query của mỗi câu để debug.
"""

import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from rag.pipeline import answer_query, FALLBACK_TEXT
from rag.retrieval import retrieve, build_search_query
from rag.prompt_builder import _detect_field_types
from rag.synthesizer import synthesizer
from rag.generator import generate_answer_1_5b
from rag.procedure_reader import procedure_reader
from rag.history_reader import history_reader

EVAL_CASES_PATH = Path(__file__).parent / "eval_cases.json"

FALLBACK_TEXTS = [
    FALLBACK_TEXT,
    "chưa đủ để trả lời",
    "không tìm thấy thông tin",
]


def is_fallback(answer: str) -> bool:
    if not answer:
        return True
    answer_lower = answer.lower()
    return any(ft.lower() in answer_lower for ft in FALLBACK_TEXTS)


def run_single_turn_eval(cases: list[dict]) -> dict:
    """Chạy eval cho các case đơn lượt."""
    results = []

    for case in cases:
        if case["type"] != "single":
            continue

        query = case["query"]
        expected_doc_id = case.get("expected_doc_id")
        expected_field = case.get("expected_field")

        # Lấy resolved_query từ synthesizer
        context = {}
        procedure_hint = procedure_reader(query=query, context=context, top_k=2)
        history = history_reader(context)

        t0 = time.monotonic()
        try:
            consolidated = synthesizer(
                query=query,
                history=history,
                procedure_hint=procedure_hint,
                generator=generate_answer_1_5b,
            )
            resolved_query = consolidated.resolved_query
        except Exception as e:
            resolved_query = query

        # Gọi pipeline
        try:
            response = answer_query(query=query, context=context)
        except Exception as e:
            response = None

        latency_ms = (time.monotonic() - t0) * 1000

        # Detect field
        detected_field = _detect_field_types(query)
        detected_field_str = detected_field[0] if detected_field else None

        # Retrieve để check doc hit
        retrieved = retrieve(query=resolved_query, context=context, top_k=1)
        top_doc_id = retrieved[0].document_id if retrieved else None
        top_score = retrieved[0].retrieval_score if retrieved else 0.0

        # Metrics
        doc_hit = (top_doc_id == expected_doc_id) if expected_doc_id else True
        field_match = (detected_field_str == expected_field) if expected_field else True
        answer_text = response.answer if response else ""
        fallback_used = is_fallback(answer_text or "")

        result = {
            "id": case["id"],
            "query": query,
            "resolved_query": resolved_query,
            "expected_doc_id": expected_doc_id,
            "top_doc_id": top_doc_id,
            "top_score": round(top_score, 3),
            "expected_field": expected_field,
            "detected_field": detected_field_str,
            "doc_hit": doc_hit,
            "field_match": field_match,
            "fallback_used": fallback_used,
            "latency_ms": round(latency_ms),
            "needs_clarification": response.needs_clarification if response else False,
        }
        results.append(result)

        status = "✓" if (doc_hit and field_match) else "✗"
        print(f"[{status}] {case['id']} | doc_hit={doc_hit} field={field_match} score={top_score:.3f} latency={latency_ms:.0f}ms")
        print(f"     Q: {query}")
        print(f"     resolved: {resolved_query}")
        if not doc_hit:
            print(f"     MISS: expected={expected_doc_id} got={top_doc_id}")
        print()

    return results


def run_multi_turn_eval(cases: list[dict]) -> dict:
    """Chạy eval cho các kịch bản multi-turn."""
    results = []

    for case in cases:
        if case["type"] != "multi_turn":
            continue

        print(f"\n=== {case['id']}: {case['description']} ===")

        context = {}
        turns_results = []
        scenario_pass = True

        for turn_idx, turn in enumerate(case["turns"]):
            query = turn["query"]
            expected_doc_id = turn.get("expected_doc_id")
            expected_field = turn.get("expected_field")

            t0 = time.monotonic()
            try:
                response = answer_query(query=query, context=context)
            except Exception as e:
                response = None
            latency_ms = (time.monotonic() - t0) * 1000

            # Get resolved query
            try:
                procedure_hint = procedure_reader(query=query, context=context, top_k=2)
                history = history_reader(context)
                consolidated = synthesizer(
                    query=query, history=history,
                    procedure_hint=procedure_hint,
                    generator=generate_answer_1_5b,
                )
                resolved_query = consolidated.resolved_query
            except Exception:
                resolved_query = query

            retrieved = retrieve(query=resolved_query, context=context, top_k=1)
            top_doc_id = retrieved[0].document_id if retrieved else None
            top_score = retrieved[0].retrieval_score if retrieved else 0.0

            doc_hit = (top_doc_id == expected_doc_id) if expected_doc_id else True
            answer_text = response.answer if response else ""
            fallback_used = is_fallback(answer_text or "")
            turn_pass = doc_hit and not fallback_used
            if not turn_pass:
                scenario_pass = False

            status = "✓" if turn_pass else "✗"
            print(f"  Turn {turn_idx+1} [{status}] | doc_hit={doc_hit} score={top_score:.3f} {latency_ms:.0f}ms")
            print(f"    Q: {query}")
            print(f"    resolved: {resolved_query}")

            turns_results.append({
                "turn": turn_idx + 1,
                "query": query,
                "resolved_query": resolved_query,
                "expected_doc_id": expected_doc_id,
                "top_doc_id": top_doc_id,
                "doc_hit": doc_hit,
                "fallback_used": fallback_used,
                "turn_pass": turn_pass,
                "latency_ms": round(latency_ms),
            })

            # Simulate updating context with assistant reply for next turn
            if response and response.answer:
                msgs = context.get("recent_messages", [])
                msgs.append({"role": "user", "content": query})
                msgs.append({"role": "assistant", "content": response.answer})
                context["recent_messages"] = msgs

        results.append({
            "id": case["id"],
            "description": case["description"],
            "scenario_pass": scenario_pass,
            "turns": turns_results,
        })

    return results


def print_summary(single_results: list, multi_results: list) -> None:
    """In bảng tổng kết metrics."""
    print("\n" + "="*60)
    print("EVAL SUMMARY")
    print("="*60)

    if single_results:
        doc_hits = [r["doc_hit"] for r in single_results]
        field_matches = [r["field_match"] for r in single_results if r["expected_field"]]
        fallbacks = [r["fallback_used"] for r in single_results]
        latencies = [r["latency_ms"] for r in single_results]

        n = len(single_results)
        print(f"\nSingle-turn ({n} cases):")
        print(f"  doc_hit@1:     {sum(doc_hits)}/{n} = {sum(doc_hits)/n*100:.1f}%")
        if field_matches:
            print(f"  field_match:   {sum(field_matches)}/{len(field_matches)} = {sum(field_matches)/len(field_matches)*100:.1f}%")
        print(f"  fallback_rate: {sum(fallbacks)}/{n} = {sum(fallbacks)/n*100:.1f}%")
        print(f"  avg_latency:   {sum(latencies)/n:.0f} ms")

        print(f"\nFailed cases:")
        for r in single_results:
            if not r["doc_hit"] or not r["field_match"]:
                print(f"  [{r['id']}] {r['query']}")
                print(f"    resolved: {r['resolved_query']}")
                if not r["doc_hit"]:
                    print(f"    doc: expected={r['expected_doc_id']} got={r['top_doc_id']} score={r['top_score']}")

    if multi_results:
        passed = [r["scenario_pass"] for r in multi_results]
        n = len(multi_results)
        print(f"\nMulti-turn ({n} scenarios):")
        print(f"  scenario_pass: {sum(passed)}/{n} = {sum(passed)/n*100:.1f}%")

        for r in multi_results:
            status = "PASS" if r["scenario_pass"] else "FAIL"
            print(f"  [{status}] {r['id']}: {r['description']}")

    print("="*60)


def main():
    print("Loading eval cases...")
    cases = json.loads(EVAL_CASES_PATH.read_text(encoding='utf-8'))
    print(f"Total cases: {len(cases)}")

    single_cases = [c for c in cases if c["type"] == "single"]
    multi_cases = [c for c in cases if c["type"] == "multi_turn"]
    print(f"Single-turn: {len(single_cases)}, Multi-turn: {len(multi_cases)}")

    print("\n" + "="*60)
    print("SINGLE-TURN EVALUATION")
    print("="*60)
    single_results = run_single_turn_eval(cases)

    print("\n" + "="*60)
    print("MULTI-TURN EVALUATION")
    print("="*60)
    multi_results = run_multi_turn_eval(cases)

    print_summary(single_results, multi_results)

    # Save results
    out = {
        "single_turn": single_results,
        "multi_turn": multi_results,
    }
    out_path = Path(__file__).parent / "eval_results.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
