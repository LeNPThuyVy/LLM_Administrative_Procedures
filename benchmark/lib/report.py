from __future__ import annotations

import json
from pathlib import Path


def all_verdicts(results: dict) -> list[dict]:
    v_list = []
    for s in results.get("suites", []):
        v_list.extend(s.get("verdicts", []))
    return v_list


def render(results: dict) -> str:
    lines = []
    tag = results.get("tag", "run")
    started = results.get("started", "")
    dur = round(results.get("duration_s", 0))
    quick_badge = "QUICK" if results.get("quick") else "FULL"

    lines.append(f"# Benchmark – {tag}")
    lines.append(f"*{started} · {dur}s · {quick_badge}*")
    lines.append("")

    verdicts = all_verdicts(results)
    n_pass = sum(1 for v in verdicts if v.get("status") == "PASS")
    n_fail = sum(1 for v in verdicts if v.get("status") == "FAIL")
    n_skip = sum(1 for v in verdicts if v.get("status") == "SKIP")
    lines.append(f"**Kết luận:** {n_pass} đạt · {n_fail} trượt · {n_skip} bỏ qua")
    lines.append("")

    # Environment
    lines.append("## Môi trường")
    lines.append("| Mục | Giá trị |")
    lines.append("|---|---|")
    for k, v in results.get("env", {}).items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    # SLO Verdicts
    lines.append("## Tổng hợp theo ngưỡng (SLO)")
    lines.append("| Chỉ số | Giá trị | Ngưỡng | KQ |")
    lines.append("|---|---|---|---|")
    for v in verdicts:
        status_icon = "✅ PASS" if v["status"] == "PASS" else ("❌ FAIL" if v["status"] == "FAIL" else "⏭️ SKIP")
        val_str = f"{v['value']:.2f}" if isinstance(v["value"], float) else str(v["value"])
        tgt_str = f"{v['op']} {v['target']}"
        lines.append(f"| {v['label']} | {val_str}{v.get('unit', '')} | {tgt_str}{v.get('unit', '')} | {status_icon} |")
    lines.append("")

    # Suite details
    for s in results.get("suites", []):
        lines.append(f"## {s.get('title', s.get('name'))}")
        for tbl in s.get("tables", []):
            lines.append(f"### {tbl.get('title', '')}")
            headers = tbl.get("headers", [])
            lines.append("| " + " | ".join(str(h) for h in headers) + " |")
            lines.append("|" + "|".join("---" for _ in headers) + "|")
            for r in tbl.get("rows", []):
                lines.append("| " + " | ".join(str(c) for c in r) + " |")
            lines.append("")

    return "\n".join(lines)


def compare(old_results: dict, new_results: dict) -> str:
    lines = ["## So sánh với lần chạy trước", "| Chỉ số | Cũ | Mới | Thay đổi |", "|---|---|---|---|"]
    old_v = {v["key"]: v for v in all_verdicts(old_results)}
    for v in all_verdicts(new_results):
        k = v["key"]
        if k in old_v:
            v_old = old_v[k]["value"]
            v_new = v["value"]
            diff = f"{v_new - v_old:+.2f}" if isinstance(v_new, (int, float)) and isinstance(v_old, (int, float)) else "-"
            lines.append(f"| {v['label']} | {v_old} | {v_new} | {diff} |")
    return "\n".join(lines)


def save(results: dict, out_dir: Path, md: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = results.get("tag", "run")
    json_path = out_dir / f"bench_{tag}.json"
    md_path = out_dir / f"bench_{tag}.md"

    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(md, encoding="utf-8")
    return json_path, md_path
