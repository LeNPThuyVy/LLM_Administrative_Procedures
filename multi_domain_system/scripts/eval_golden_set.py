"""
scripts/eval_golden_set.py — Golden Set Evaluator for Qdrant Retrieval.

Measures Retrieval@1, @3, @5 and MRR (Mean Reciprocal Rank) on golden set.

Usage:
    python scripts/eval_golden_set.py [--domain administrative_procedures] [--top-k 5]
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

def load_golden_set(domain: str) -> tuple[list[dict], Path]:
    domain_golden = ROOT_DIR / "domains" / domain / "golden_set.json"
    if domain_golden.exists():
        print(f"Loading golden set from: {domain_golden}")
        return json.loads(domain_golden.read_text(encoding="utf-8")), domain_golden
    
    fallback_eval = ROOT_DIR / "test" / "eval_cases.json"
    if fallback_eval.exists():
        print(f"Domain golden set not found ({domain_golden}). Loading fallback cases from: {fallback_eval}")
        raw_cases = json.loads(fallback_eval.read_text(encoding="utf-8"))
        formatted = []
        for c in raw_cases:
            if c.get("type") == "single":
                formatted.append({
                    "id": c.get("id"),
                    "question": c.get("query"),
                    "expected_document_id": c.get("expected_doc_id"),
                    "expected_field": c.get("expected_field"),
                })
        return formatted, fallback_eval

    raise FileNotFoundError(f"No golden set found at {domain_golden} or {fallback_eval}")

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Golden Set Retrieval Evaluator")
    parser.add_argument("--domain", default="administrative_procedures", help="Domain ID")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K candidates")
    args = parser.parse_args()

    questions, golden_file = load_golden_set(args.domain)
    from rag.retrieval import retrieve

    print("\n" + "=" * 60, flush=True)
    print(f"EVALUATING RETRIEVAL ON GOLDEN SET ({len(questions)} cases) - Domain: {args.domain}", flush=True)
    print("=" * 60, flush=True)

    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(args.domain)
    min_score = getattr(runtime, "min_retrieval_score", 0.5)

    hits_r1 = 0
    hits_r3 = 0
    hits_r5 = 0
    mrr_sum = 0.0
    field_match_count = 0
    field_eval_total = 0

    in_scope_total = 0
    out_scope_total = 0
    out_scope_pass = 0

    eval_details = []

    for q in questions:
        qid = q.get("id", "N/A")
        query_text = q.get("question") or q.get("query", "")
        exp_doc = q.get("expected_document_id") or q.get("expected_proc_id")
        exp_field = q.get("expected_field")

        results = retrieve(query=query_text, top_k=max(args.top_k, 5), domain=args.domain)
        retrieved_ids = [r.document_id for r in results]
        retrieved_fields = [r.metadata.get("field") for r in results]
        top_score = float(results[0].retrieval_score) if results else 0.0
        top3_display = retrieved_ids[:3]

        if exp_doc is not None:
            # IN-SCOPE CASE
            in_scope_total += 1
            rank = 0
            if isinstance(exp_doc, list):
                ranks = [retrieved_ids.index(d) + 1 for d in exp_doc if d in retrieved_ids]
                rank = min(ranks) if ranks else 0
            elif exp_doc in retrieved_ids:
                rank = retrieved_ids.index(exp_doc) + 1

            r1 = (rank == 1)
            r3 = (1 <= rank <= 3)
            r5 = (1 <= rank <= 5)
            reciprocal_rank = 1.0 / rank if rank > 0 else 0.0

            if r1: hits_r1 += 1
            if r3: hits_r3 += 1
            if r5: hits_r5 += 1
            mrr_sum += reciprocal_rank

            field_ok = None
            if exp_field:
                field_eval_total += 1
                got_field = retrieved_fields[0] if retrieved_fields else None
                field_ok = (got_field == exp_field)
                if field_ok:
                    field_match_count += 1

            status = "✓" if r5 else "✗"
            print(f"[{status}] [{qid}] {query_text[:50]}...", flush=True)
            print(f"     Expected: {exp_doc} | Got Top 3: {top3_display} | Score: {top_score:.3f} | Rank: {rank if rank else 'N/A'}", flush=True)

            eval_details.append({
                "id": qid,
                "type": "in_scope",
                "question": query_text,
                "expected_document_id": exp_doc,
                "expected_field": exp_field,
                "rank": rank,
                "retrieved_top3": top3_display,
                "top_score": top_score,
                "r1": r1,
                "r5": r5,
            })
        else:
            # OUT-OF-SCOPE CASE (Check rejection)
            out_scope_total += 1
            rejected = (not results or top_score < min_score)
            if rejected:
                out_scope_pass += 1
                status = "✓"
                verdict = f"REJECTED (score={top_score:.3f} < {min_score})"
            else:
                status = "✗"
                verdict = f"FALSE_POSITIVE (score={top_score:.3f} >= {min_score}, doc={top3_display[0] if top3_display else 'N/A'})"

            print(f"[{status}] [{qid}] [OUT-OF-SCOPE] {query_text[:45]}...", flush=True)
            print(f"     Verdict: {verdict}", flush=True)

            eval_details.append({
                "id": qid,
                "type": "out_of_scope",
                "question": query_text,
                "expected_document_id": None,
                "top_score": top_score,
                "rejected": rejected,
                "min_score_threshold": min_score,
            })

    total = len(questions) or 1
    in_total = in_scope_total or 1
    r1_pct = (hits_r1 / in_total) * 100
    r3_pct = (hits_r3 / in_total) * 100
    r5_pct = (hits_r5 / in_total) * 100
    mrr = mrr_sum / in_total

    print("\n" + "=" * 60, flush=True)
    print(f"EVALUATION SUMMARY — {args.domain.upper()}", flush=True)
    print("=" * 60, flush=True)
    print(f"Total Questions : {total} (In-scope: {in_scope_total}, Out-of-scope: {out_scope_total})", flush=True)
    print(f"Retrieval@1     : {hits_r1}/{in_scope_total} ({r1_pct:.1f}%)", flush=True)
    print(f"Retrieval@3     : {hits_r3}/{in_scope_total} ({r3_pct:.1f}%)", flush=True)
    print(f"Retrieval@5     : {hits_r5}/{in_scope_total} ({r5_pct:.1f}%)", flush=True)
    print(f"MRR             : {mrr:.4f}", flush=True)
    if field_eval_total > 0:
        print(f"Field Match     : {field_match_count}/{field_eval_total} ({field_match_count/field_eval_total*100:.1f}%)", flush=True)
    if out_scope_total > 0:
        rej_pct = (out_scope_pass / out_scope_total) * 100
        print(f"Rejection Acc   : {out_scope_pass}/{out_scope_total} ({rej_pct:.1f}%)", flush=True)
    print("=" * 60, flush=True)

    # Save report
    out_dir = ROOT_DIR / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    out_path = out_dir / f"eval_golden_set_{args.domain}_{date_str}.json"

    report = {
        "timestamp": datetime.now().isoformat(),
        "domain": args.domain,
        "total": total,
        "in_scope_total": in_scope_total,
        "out_scope_total": out_scope_total,
        "retrieval_at_1": r1_pct,
        "retrieval_at_3": r3_pct,
        "retrieval_at_5": r5_pct,
        "mrr": mrr,
        "out_scope_rejection_acc": (out_scope_pass / out_scope_total * 100) if out_scope_total else None,
        "details": eval_details,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved eval results to: {out_path}", flush=True)

    if args.domain == "administrative_procedures":
        compat_path = out_dir / f"eval_golden_set_{date_str}.json"
        compat_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    
    sys.stdout.flush()
    sys.stderr.flush()

if __name__ == "__main__":
    main()
    os._exit(0)

