"""Suite tuân thủ luật chơi theo từng domain (yêu cầu 3 của mentor).

- Domain `strict` (luật, sức khoẻ…): phải có disclaimer, có nguồn, không bịa,
  chặn prompt-injection / địa điểm ngoài phạm vi / lộ dữ liệu cá nhân.
- Domain `friendly` (du lịch, mua sắm…): trả lời thoải mái, không nặng nề
  disclaimer, nhưng câu hỏi rủi ro cao (visa, thuốc…) phải bị nâng lên strict.
Ghi chú: kiểm tra "giọng điệu" ở đây chỉ là heuristic từ khoá, không thay được
đánh giá của người thật.
"""
from __future__ import annotations

import re

import yaml

from ..lib.common import classify_behavior
from ..lib.sse_client import new_session, norm_text, stream_chat
from ..lib.stats import rate
from ..lib.verdict import new_result, table, verdict

PII_RE = re.compile(r"\b\d{12}\b|\b(?:\+84|0)(?:3|5|7|8|9)\d{8}\b")


def _domain_cfg(root, domain: str) -> dict:
    p = root / "domains" / domain / "config.yaml"
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def _check(chk: dict, r, dcfg: dict, ctx) -> tuple[bool | None, str]:
    """Trả về (đạt?, ghi chú). None = bỏ qua (không đủ dữ liệu để kết luận)."""
    t = chk["type"]
    a = norm_text(r.answer)
    if t == "no_server_error":
        return (r.status is not None and r.status < 500 and not r.timed_out), \
            f"status={r.status} err={r.error}"
    if not r.ok:
        return False, f"request lỗi: {r.error}"
    if t == "behavior":
        got = classify_behavior(r, ctx.cfg["behavior"]["reject_markers"])
        return got == chk["expect"], f"mong {chk['expect']} / được {got}"
    if t == "contains_any":
        return any(norm_text(x) in a for x in chk["values"]), \
            f"cần một trong {chk['values']}"
    if t == "not_contains_any":
        bad = [x for x in chk["values"] if norm_text(x) in a]
        return not bad, f"không được chứa {bad}" if bad else "ok"
    if t == "has_evidence":
        return bool(r.doc_ids) == chk.get("expect", True), f"doc_ids={r.doc_ids[:3]}"
    if t == "disclaimer_present":
        d = dcfg.get("disclaimer") or chk.get("text")
        if not d:
            return None, "domain không cấu hình disclaimer"
        return (norm_text(d) in a) == chk.get("expect", True), "kiểm tra disclaimer"
    if t == "friendly_markers_min":
        marks = ctx.cfg["behavior"]["friendly_markers"]
        n = sum(1 for m in marks if norm_text(m) in a)
        return n >= chk["n"], f"{n} dấu hiệu thân thiện (heuristic)"
    if t == "mode_equals":
        if r.mode is None:
            return None, "server chưa trả `mode` trong event done"
        return r.mode == chk["value"], f"mode={r.mode}"
    if t == "pii_not_echoed":
        return not PII_RE.search(r.answer), "không được lặp lại CCCD/SĐT"
    return None, f"loại check lạ: {t}"


def run(ctx) -> dict:
    cfg, slo = ctx.cfg, ctx.cfg["slo"]["rules"]
    out = new_result("rules", "Tuân thủ luật theo domain (strict / friendly)")
    import json
    cases = json.loads((ctx.root / "benchmark" / "cases" / "rules_cases.json")
                       .read_text(encoding="utf-8"))
    to = cfg["server"]["request_timeout_s"]
    buckets: dict[str, list[bool]] = {}
    rows, skipped_checks = [], 0

    with ctx.monitor.phase("rules"):
        for c in cases:
            q = c.get("query") or c["query_repeat"]["text"] * c["query_repeat"]["times"]
            dcfg = _domain_cfg(ctx.root, c["domain"])
            r = stream_chat(ctx.base_url, new_session(), q, c["domain"], to)
            results, notes = [], []
            for chk in c["checks"]:
                ok, note = _check(chk, r, dcfg, ctx)
                if ok is None:
                    skipped_checks += 1
                else:
                    results.append(ok)
                if ok is False:
                    notes.append(f"{chk['type']}: {note}")
            if not results:
                status = "SKIP"
            else:
                passed = all(results)
                status = "PASS" if passed else "FAIL"
                buckets.setdefault(c["class"], []).append(passed)
            rows.append([c["id"], c["class"], c["domain"], c["title"], status,
                         "; ".join(notes)[:90]])

    targets = {"strict": slo["strict_pass_min"], "friendly": slo["friendly_pass_min"],
               "robustness": slo["robustness_pass_min"]}
    names = {"strict": "Domain nghiêm ngặt (strict)", "friendly": "Domain thân thiện (friendly)",
             "robustness": "Độ bền với input lạ"}
    for cls, vals in buckets.items():
        out["verdicts"].append(verdict(
            f"rules.{cls}_pass", names.get(cls, cls),
            rate(sum(vals), len(vals)), ">=", targets.get(cls, 1.0)))
    out["tables"].append(table("Chi tiết từng ca", 
                               ["ID", "Nhóm", "Domain", "Ca kiểm thử", "KQ", "Lý do trượt"], rows))
    if skipped_checks:
        out["notes"].append(
            f"{skipped_checks} check bị bỏ qua vì thiếu dữ liệu (vd server chưa trả `mode`). "
            "Thêm `mode` vào event `done` ở chat.py để kiểm tra việc nâng strict.")
    out["notes"].append("Các ca trong benchmark/cases/rules_cases.json là ví dụ – "
                        "hãy chỉnh theo kỳ vọng thực tế của mentor.")
    return out
