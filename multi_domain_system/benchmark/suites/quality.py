"""Suite chất lượng: đúng tài liệu, đúng nội dung, đúng hành vi (trả lời/hỏi lại/từ chối)."""
from __future__ import annotations

import time
from collections import defaultdict

from ..lib.common import (classify_behavior, doc_match, keyword_recall,
                          load_golden, load_scenarios)
from ..lib.sse_client import new_session, stream_chat
from ..lib.stats import rate
from ..lib.verdict import new_result, table, verdict


def run(ctx) -> dict:
    cfg, slo = ctx.cfg, ctx.cfg["slo"]["quality"]
    out = new_result("quality", "Chất lượng trả lời")
    markers = cfg["behavior"]["reject_markers"]
    gap = cfg["behavior"].get("multi_turn_gap_s", 2.0)
    to = cfg["server"]["request_timeout_s"]
    max_cases = ctx.q("quality", "max_cases")

    with ctx.monitor.phase("quality"):
        for ds in cfg["datasets"]:
            dom = ds["domain"]
            cases = load_golden(ds, ctx.root, max_cases, ctx.seed)

            # ---------- golden set ----------
            doc_hits = doc_total = errors = 0
            kw_scores, kw_all = [], []
            by_field = defaultdict(lambda: [0, 0])  # field -> [hit, total]
            fails = []
            for c in cases:
                r = stream_chat(ctx.base_url, new_session(), c["query"], dom, to)
                if not r.ok:
                    errors += 1
                    fails.append([c["id"], c["query"][:60], "LỖI: " + str(r.error)[:40], "-"])
                    continue
                if c["expected_docs"]:
                    doc_total += 1
                    hit = doc_match(c["expected_docs"], r.doc_ids)
                    doc_hits += hit
                    by_field[c["field"]][1] += 1
                    by_field[c["field"]][0] += hit
                    if not hit:
                        fails.append([c["id"], c["query"][:60],
                                      ",".join(c["expected_docs"]),
                                      ",".join(r.doc_ids[:3]) or "(không có evidence)"])
                kr = keyword_recall(r.answer, c["keywords"])
                if kr is not None:
                    kw_scores.append(kr)
                    kw_all.append(kr == 1.0)

            n = len(cases)
            doc_rate = rate(doc_hits, doc_total)
            kw_mean = sum(kw_scores) / len(kw_scores) if kw_scores else None
            out["verdicts"] += [
                verdict(f"quality.{dom}.doc_hit", f"[{dom}] Đúng tài liệu (qua evidence)",
                        doc_rate, ">=", slo["doc_hit_min"]),
                verdict(f"quality.{dom}.keyword_recall", f"[{dom}] Độ phủ từ khoá kỳ vọng",
                        kw_mean, ">=", slo["keyword_recall_min"]),
                verdict(f"quality.{dom}.error_rate", f"[{dom}] Tỉ lệ lỗi request",
                        rate(errors, n), "<=", slo["error_rate_max"]),
            ]
            out["tables"].append(table(
                f"Golden set – {dom} ({n} câu)",
                ["Chỉ số", "Giá trị"],
                [["Đúng tài liệu", f"{doc_hits}/{doc_total}"],
                 ["Đủ 100% từ khoá", f"{sum(kw_all)}/{len(kw_all)}"],
                 ["Độ phủ từ khoá TB", kw_mean],
                 ["Request lỗi", errors]]))
            if len(by_field) > 1:
                out["tables"].append(table(
                    f"Đúng tài liệu theo loại thông tin – {dom}",
                    ["Field", "Đúng", "Tổng", "Tỉ lệ"],
                    [[f, h, t, rate(h, t)] for f, (h, t) in sorted(by_field.items())]))
            if fails:
                out["tables"].append(table(
                    f"Câu sai (tối đa 15) – {dom}",
                    ["ID", "Câu hỏi", "Kỳ vọng", "Thực tế"], fails[:15]))

            # ---------- kịch bản hành vi / nhiều lượt ----------
            scen = load_scenarios(ds, ctx.root)
            if not scen:
                continue
            rows, passed, total = [], 0, 0
            for s in scen:
                turns = s["turns"] if s.get("type") == "multi_turn" else [s]
                sid = new_session()
                for i, t in enumerate(turns, 1):
                    r = stream_chat(ctx.base_url, sid if s.get("type") == "multi_turn"
                                    else new_session(), t["query"], dom, to)
                    exp = t.get("expected_behavior", "ANSWER")
                    got = classify_behavior(r, markers)
                    ok = got == exp
                    if ok and exp == "ANSWER" and t.get("expected_doc_id"):
                        ok = doc_match(t["expected_doc_id"], r.doc_ids)
                    total += 1
                    passed += ok
                    rows.append([f"{s['id']}#{i}", t["query"][:55], exp, got,
                                 "PASS" if ok else "FAIL"])
                    if s.get("type") == "multi_turn":
                        time.sleep(gap)  # chờ update_memory (chạy nền) xong
            out["verdicts"].append(verdict(
                f"quality.{dom}.scenario_pass", f"[{dom}] Kịch bản hành vi + nhiều lượt",
                rate(passed, total), ">=", slo["behavior_pass_min"]))
            out["tables"].append(table(
                f"Kịch bản hành vi – {dom} ({passed}/{total} đạt)",
                ["Lượt", "Câu hỏi", "Kỳ vọng", "Thực tế", "KQ"], rows))

    out["notes"].append(
        "Đúng tài liệu được suy ra từ `document_id` trong evidence/citation của "
        "response: câu trả lời đúng nhưng không kèm citation vẫn tính là trượt "
        "(đây cũng là kiểm tra khả năng truy vết nguồn).")
    return out
