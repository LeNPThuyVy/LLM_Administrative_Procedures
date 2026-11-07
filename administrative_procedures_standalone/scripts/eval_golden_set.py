"""
scripts/eval_golden_set.py — Golden Set & Pipeline Evaluator.

Measures:
- Retrieval@1, @3, @5 and MRR (Mean Reciprocal Rank)
- Field Match (top-1 chunk field vs expected_field, plus confusion matrix)
- Out-of-Scope Rejection Accuracy & In-Scope False Rejection Rate
- Unsupported Claim Leak Rate (in --mode pipeline)

Usage:
    py -3.12 scripts/eval_golden_set.py [--domain administrative_procedures] [--mode two_step|pipeline|retrieval]
"""

import os
import sys
import json
import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


def _parse_expected_docs(exp_doc, exp_behavior: str | None = None) -> list[str] | None:
    """Return list of valid expected document IDs for in-scope, or None for out-of-scope."""
    if exp_behavior and str(exp_behavior).strip().upper() in ("REJECT", "OUT_OF_SCOPE", "CLARIFY"):
        return None
    if exp_doc is None:
        return None
    if isinstance(exp_doc, str):
        s = exp_doc.strip()
        if not s or s.upper() in ("NONE", "NULL", "OUT_OF_SCOPE", "CLARIFY/NONE", "CLARIFY"):
            return None
        if "," in s:
            return [part.strip() for part in s.split(",") if part.strip()]
        return [s]
    if isinstance(exp_doc, list):
        cleaned = [str(item).strip() for item in exp_doc if str(item).strip()]
        return cleaned if cleaned else None
    return [str(exp_doc)]


def _infer_chunk_field(chunk) -> str | None:
    """Extract normalized field name from chunk metadata or chunk_id suffix."""
    meta_field = (chunk.metadata or {}).get("field")
    if meta_field:
        if meta_field == "submission_location":
            return "submission_method"
        return str(meta_field)
    cid = str(getattr(chunk, "chunk_id", "") or "")
    suffix_map = {
        "_docs": "required_documents",
        "_fee": "fee",
        "_time": "processing_time",
        "_method": "submission_method",
        "_general": "general",
    }
    for suf, fname in suffix_map.items():
        if cid.endswith(suf):
            return fname
    return None


def load_golden_set(domain: str, extra_cases_path: str | None = None, split_filter: str = "all") -> tuple[list[dict], Path]:
    domain_golden = ROOT_DIR / "domains" / domain / "golden_set.json"
    if not domain_golden.exists():
        raise FileNotFoundError(f"No golden set found at {domain_golden}")

    cases = json.loads(domain_golden.read_text(encoding="utf-8"))
    if extra_cases_path:
        extra_p = Path(extra_cases_path)
        if extra_p.exists():
            extra_data = json.loads(extra_p.read_text(encoding="utf-8"))
            cases.extend(extra_data)

    if split_filter and split_filter != "all":
        cases = [c for c in cases if c.get("split", "golden") == split_filter]

    return cases, domain_golden


def _is_rejection_response(resp, runtime) -> bool:
    """Check if an AnswerResponse represents an out-of-scope / clarification / no-evidence rejection."""
    if getattr(resp, "needs_clarification", False):
        return True
    ans = (getattr(resp, "answer", "") or "").strip().lower()
    if not ans:
        return True
    rejection_markers = [
        "chưa có đủ thông tin",
        "chưa đủ để trả lời",
        "ngoài phạm vi",
        "không thuộc thẩm quyền",
        "chỉ hỗ trợ tra cứu",
        "chỉ hỗ trợ thông tin thủ tục hành chính tại",
        "chưa có trong cơ sở dữ liệu",
        "bạn muốn hỏi hoặc thực hiện thủ tục hành chính nào",
        "bạn muốn hỏi về nội dung",
        "vui lòng cung cấp thêm thông tin cụ thể",
        "vi phạm quy tắc an toàn",
        "không thể tư vấn về y tế",
    ]
    if runtime:
        for msg in (
            getattr(runtime, "no_evidence_message", ""),
            getattr(runtime.config, "out_of_scope_message", ""),
            getattr(runtime, "clarification_prompt", ""),
        ):
            if msg and msg.strip().lower()[:30] in ans:
                return True
    return any(m in ans for m in rejection_markers)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Golden Set & Pipeline Evaluator")
    parser.add_argument("--domain", default="administrative_procedures", help="Domain ID")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K candidates")
    parser.add_argument(
        "--mode",
        choices=["retrieval", "two_step", "pipeline"],
        default="two_step",
        help="Evaluation mode: raw 'retrieval', 'two_step' (with field & OOS gates), or full 'pipeline'",
    )
    parser.add_argument("--extra-cases", default=None, help="Optional path to extra OOS/in-scope test cases JSON")
    parser.add_argument("--split", choices=["all", "golden", "dev", "held_out"], default="all", help="Dataset split filter")
    parser.add_argument("--save-report", action="store_true", help="Save JSON report to task/ directory")
    args = parser.parse_args()

    questions, golden_file = load_golden_set(args.domain, args.extra_cases, args.split)
    from rag.retrieval import retrieve, retrieve_two_step
    from rag.text_normalizer import normalize_query_text
    from domains.runtime import get_domain_runtime

    runtime = get_domain_runtime(args.domain)
    min_score = getattr(runtime, "min_retrieval_score", 0.5)

    print("\n" + "=" * 70, flush=True)
    print(
        f"EVALUATING GOLDEN SET ({len(questions)} cases) | Domain: {args.domain} | Mode: {args.mode} | Split: {args.split}",
        flush=True,
    )
    print("=" * 70, flush=True)

    hits_r1 = 0
    hits_r3 = 0
    hits_r5 = 0
    mrr_sum = 0.0
    field_match_count = 0
    field_eval_total = 0
    field_confusion: Counter = Counter()

    in_scope_total = 0
    in_scope_false_reject = 0
    out_scope_total = 0
    out_scope_pass = 0

    unsupported_leak_cases = 0
    evaluated_answer_cases = 0
    keyword_hits = 0
    keyword_total = 0
    incomplete_answer_cases = 0

    eval_details = []

    for q in questions:
        qid = q.get("id", "N/A")
        query_text = q.get("question") or q.get("query", "")
        raw_exp_doc = q.get("expected_document_id") if "expected_document_id" in q else q.get("expected_proc_id")
        exp_behavior = q.get("expected_behavior")
        exp_docs = _parse_expected_docs(raw_exp_doc, exp_behavior)
        exp_field = q.get("expected_field")
        if exp_field == "submission_location":
            exp_field = "submission_method"

        norm_q = normalize_query_text(query_text) if args.mode in ("two_step", "pipeline") else query_text

        rejected_by_gate = False
        has_unsupported_leak = False

        if args.mode == "retrieval":
            results = retrieve(query=query_text, top_k=max(args.top_k, 5), domain=args.domain)
        elif args.mode == "two_step":
            import rag.pipeline as _pipe_mod
            from rag.pipeline import _detect_unsupported_location
            from rag.synthesizer import _is_vague_or_greeting
            _is_out_of_scope_query = getattr(_pipe_mod, "_is_out_of_scope_query", lambda *a, **k: False)
            if _detect_unsupported_location(norm_q, domain=args.domain) or _is_vague_or_greeting(norm_q, domain=args.domain):
                rejected_by_gate = True
                results = []
            elif _is_out_of_scope_query(norm_q, domain=args.domain):
                rejected_by_gate = True
                results = []
            else:
                raw_res = retrieve(query=norm_q, top_k=max(args.top_k, 5) * 3, domain=args.domain)
                if not raw_res:
                    rejected_by_gate = True
                    results = []
                else:
                    results = retrieve_two_step(
                        query=norm_q,
                        top_k=max(args.top_k, 5),
                        domain=args.domain,
                        raw_results=raw_res,
                    )
                    if not results:
                        rejected_by_gate = True
                    elif results[0].retrieval_score < min_score:
                        rejected_by_gate = True
        else:
            # Full pipeline mode
            from rag.pipeline import answer_query
            resp = answer_query(query=query_text, domain=args.domain)
            rejected_by_gate = _is_rejection_response(resp, runtime)
            raw_res = retrieve(query=norm_q, top_k=max(args.top_k, 5) * 3, domain=args.domain)
            results = retrieve_two_step(
                query=norm_q,
                top_k=max(args.top_k, 5),
                domain=args.domain,
                raw_results=raw_res,
            ) if raw_res else []
            if not rejected_by_gate:
                evaluated_answer_cases += 1
                claims = getattr(resp, "claims", []) or []
                if any(getattr(c, "status", "") == "unsupported" for c in claims):
                    has_unsupported_leak = True
                    unsupported_leak_cases += 1

                # Bộ lọc strict bỏ cả claim `partial`, nên đo xem câu trả lời
                # còn đủ ý kỳ vọng hay đã bị cắt thiếu.
                expected_keywords = q.get("expected_keywords") or []
                if expected_keywords and exp_docs is not None:
                    from rag.text_normalizer import fold_accents
                    folded_answer = fold_accents(resp.answer or "").lower()
                    found = sum(
                        1 for keyword in expected_keywords
                        if fold_accents(str(keyword)).lower() in folded_answer
                    )
                    keyword_hits += found
                    keyword_total += len(expected_keywords)
                    if found < len(expected_keywords):
                        incomplete_answer_cases += 1

        retrieved_ids = []
        for r in results:
            if r.document_id not in retrieved_ids:
                retrieved_ids.append(r.document_id)
        all_chunk_doc_ids = [r.document_id for r in results]
        retrieved_fields = [_infer_chunk_field(r) for r in results]
        top_score = float(results[0].retrieval_score) if results else 0.0
        top3_display = retrieved_ids[:3]

        if exp_docs is not None:
            # IN-SCOPE CASE
            in_scope_total += 1
            if rejected_by_gate:
                in_scope_false_reject += 1

            ranks = [all_chunk_doc_ids.index(d) + 1 for d in exp_docs if d in all_chunk_doc_ids]
            rank = min(ranks) if ranks else 0

            r1 = (rank == 1)
            r3 = (1 <= rank <= 3)
            r5 = (1 <= rank <= 5)
            reciprocal_rank = 1.0 / rank if rank > 0 else 0.0

            if r1:
                hits_r1 += 1
            if r3:
                hits_r3 += 1
            if r5:
                hits_r5 += 1
            mrr_sum += reciprocal_rank

            field_ok = None
            got_field = retrieved_fields[0] if retrieved_fields else None
            if exp_field:
                field_eval_total += 1
                field_ok = (got_field == exp_field)
                if field_ok:
                    field_match_count += 1
                else:
                    field_confusion[(exp_field, got_field or "NONE")] += 1

            status = "✓" if (r5 and (field_ok is not False) and not rejected_by_gate) else "✗"
            print(
                f"[{status}] [{qid}] {query_text[:52]}... | DocRank={rank or 'MISS'} "
                f"| Field={got_field} (exp={exp_field}) | GateRej={rejected_by_gate}",
                flush=True,
            )

            eval_details.append({
                "id": qid,
                "type": "in_scope",
                "question": query_text,
                "expected_document_id": exp_docs,
                "expected_field": exp_field,
                "got_field": got_field,
                "field_match": field_ok,
                "rank": rank,
                "retrieved_top3": top3_display,
                "top_score": top_score,
                "r1": r1,
                "r5": r5,
                "false_rejected": rejected_by_gate,
                "unsupported_leak": has_unsupported_leak,
            })
        else:
            # OUT-OF-SCOPE CASE
            out_scope_total += 1
            rejected = rejected_by_gate or (not results) or (top_score < min_score)
            if rejected:
                out_scope_pass += 1
                status = "✓"
                verdict = f"REJECTED (gate={rejected_by_gate}, score={top_score:.3f})"
            else:
                status = "✗"
                verdict = f"FALSE_POSITIVE (score={top_score:.3f} >= {min_score}, doc={top3_display[0] if top3_display else 'N/A'})"

            print(f"[{status}] [{qid}] [OOS] {query_text[:48]}... -> {verdict}", flush=True)

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
    fm_pct = (field_match_count / field_eval_total * 100) if field_eval_total else 0.0
    rej_pct = (out_scope_pass / out_scope_total * 100) if out_scope_total else 0.0
    false_rej_pct = (in_scope_false_reject / in_total * 100) if in_scope_total else 0.0

    print("\n" + "=" * 70, flush=True)
    print(f"EVALUATION SUMMARY — {args.domain.upper()} (mode={args.mode}, split={args.split})", flush=True)
    print("=" * 70, flush=True)
    print(f"Total Questions      : {total} (In-scope: {in_scope_total}, Out-of-scope: {out_scope_total})", flush=True)
    print(f"Retrieval@1          : {hits_r1}/{in_scope_total} ({r1_pct:.1f}%)", flush=True)
    print(f"Retrieval@3          : {hits_r3}/{in_scope_total} ({r3_pct:.1f}%)", flush=True)
    print(f"Retrieval@5          : {hits_r5}/{in_scope_total} ({r5_pct:.1f}%)", flush=True)
    print(f"MRR                  : {mrr:.4f}", flush=True)
    if field_eval_total > 0:
        print(f"Field Match          : {field_match_count}/{field_eval_total} ({fm_pct:.1f}%)", flush=True)
    if field_confusion:
        print(f"Field Confusions     : {dict(field_confusion)}", flush=True)
    if out_scope_total > 0:
        print(f"OOS Rejection Acc    : {out_scope_pass}/{out_scope_total} ({rej_pct:.1f}%)", flush=True)
    print(f"In-Scope False Rej   : {in_scope_false_reject}/{in_scope_total} ({false_rej_pct:.1f}%)", flush=True)
    if args.mode == "pipeline":
        print(f"Unsupported Claim Ca : {unsupported_leak_cases}/{evaluated_answer_cases}", flush=True)
        if keyword_total:
            print(f"Keyword Coverage     : {keyword_hits}/{keyword_total} ({keyword_hits / keyword_total * 100:.1f}%)", flush=True)
            print(f"Thiếu từ khóa kỳ vọng: {incomplete_answer_cases}/{evaluated_answer_cases} ca", flush=True)
    print("=" * 70, flush=True)

    if args.save_report:
        task_dir = ROOT_DIR.parent / "task" if (ROOT_DIR.parent / "task").exists() else (ROOT_DIR / "task")
        task_dir.mkdir(parents=True, exist_ok=True)
        out_path = task_dir / f"eval_report_{args.domain}_{args.mode}_{args.split}.json"
        report = {
            "timestamp": datetime.now().isoformat(),
            "domain": args.domain,
            "mode": args.mode,
            "split": args.split,
            "total": total,
            "in_scope_total": in_scope_total,
            "out_scope_total": out_scope_total,
            "retrieval_at_1": r1_pct,
            "retrieval_at_3": r3_pct,
            "retrieval_at_5": r5_pct,
            "mrr": mrr,
            "field_match_pct": fm_pct,
            "out_scope_rejection_acc": rej_pct,
            "in_scope_false_rejection_pct": false_rej_pct,
            "unsupported_leak_cases": unsupported_leak_cases,
            "keyword_hits": keyword_hits,
            "keyword_total": keyword_total,
            "incomplete_answer_cases": incomplete_answer_cases,
            "details": eval_details,
        }
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved eval results to: {out_path}", flush=True)


if __name__ == "__main__":
    main()
    os._exit(0)
