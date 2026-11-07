"""Sinh báo cáo Markdown (tiếng Việt) và so sánh giữa hai lần chạy."""
from __future__ import annotations

import json
from pathlib import Path

ICON = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "SKIP": "⏭ SKIP"}


def _v(x) -> str:
    if x is None:
        return "–"
    if isinstance(x, bool):
        return "có" if x else "không"
    if isinstance(x, float):
        return f"{x:.2f}" if abs(x) < 1000 else f"{x:,.0f}"
    return str(x)


def _md_table(headers, rows) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(_v(c).replace("|", "/") for c in r) + " |")
    return "\n".join(lines)


def all_verdicts(results: dict) -> list[dict]:
    return [v for s in results["suites"] for v in s["verdicts"]]


def render(results: dict) -> str:
    env, vs = results["env"], all_verdicts(results)
    cnt = {k: sum(1 for v in vs if v["status"] == k) for k in ICON}
    md = [f"# Benchmark – {results['tag']}",
          f"*{results['started']} · {results['duration_s']:.0f}s · "
          f"{'QUICK' if results['quick'] else 'FULL'}*", "",
          f"**Kết luận:** {cnt['PASS']} đạt · {cnt['FAIL']} trượt · {cnt['SKIP']} bỏ qua", ""]

    md += ["## Môi trường", _md_table(["Mục", "Giá trị"], [[k, v] for k, v in env.items()]), ""]

    md += ["## Tổng hợp theo ngưỡng (SLO)",
           _md_table(["Chỉ số", "Giá trị", "Ngưỡng", "KQ"],
                     [[v["label"], f"{_v(v['value'])}{v['unit']}",
                       f"{v['op']} {_v(v['target'])}{v['unit']}" if v["target"] is not None else "–",
                       ICON[v["status"]]] for v in vs]), ""]

    if results.get("resources"):
        md += ["## Tài nguyên (RAM / CPU / GPU) theo giai đoạn",
               _md_table(["Giai đoạn", "RAM đỉnh (MB)", "API đỉnh", "LLM đỉnh", "RAM TB",
                          "CPU TB %", "CPU đỉnh %", "GPU đỉnh (MB)", "Thread đỉnh"],
                         [[p, s["peak_mb"], s["peak_api_mb"], s["peak_llm_mb"], s["avg_mb"],
                           s["cpu_avg"], s["cpu_peak"], s["gpu_peak_mb"], s["threads_peak"]]
                          for p, s in results["resources"].items()]), ""]
    else:
        md += ["## Tài nguyên", "> Không tìm thấy process server để đo RAM. "
               "Dùng `--pid <PID>` hoặc kiểm tra `watch_ports`.", ""]

    for s in results["suites"]:
        md += [f"## {s['title']}"]
        for t in s["tables"]:
            md += [f"**{t['title']}**", "", _md_table(t["headers"], t["rows"]), ""]
        for n in s["notes"]:
            md.append(f"> {n}")
        md.append("")
    return "\n".join(md)


# --------------------------------------------------------------- so sánh
def compare(old: dict, new: dict) -> str:
    o = {v["key"]: v for v in all_verdicts(old)}
    rows = []
    for v in all_verdicts(new):
        p = o.get(v["key"])
        if not p or v["value"] is None or p["value"] is None:
            continue
        a, b = p["value"], v["value"]
        delta = (b - a) / a * 100 if a else 0.0
        better = (b < a) if v["op"] == "<=" else (b > a)
        mark = "=" if abs(delta) < 2 else ("🟢 tốt hơn" if better else "🔴 tệ hơn")
        rows.append([v["label"], a, b, f"{delta:+.1f}%", mark])
    if not rows:
        return ""
    return ("## So sánh với lần chạy trước (" + old["tag"] + ")\n\n"
            + _md_table(["Chỉ số", "Trước", "Sau", "Δ", ""], rows) + "\n")


def save(results: dict, out_dir: Path, md: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"bench_{results['tag']}"
    jp, mp = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    jp.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str),
                  encoding="utf-8")
    mp.write_text(md, encoding="utf-8")
    return jp, mp
