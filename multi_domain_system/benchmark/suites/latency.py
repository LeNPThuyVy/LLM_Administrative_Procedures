"""Suite độ trễ khi chỉ có 1 người dùng (chưa tải): TTFT, tổng thời gian, tốc độ sinh, cache."""
from __future__ import annotations

import time
from collections import defaultdict

from ..lib.common import load_golden
from ..lib.sse_client import new_session, stream_chat
from ..lib.stats import percentile, summarize
from ..lib.verdict import new_result, table, verdict


def run(ctx) -> dict:
    cfg, slo = ctx.cfg, ctx.cfg["slo"]["latency"]
    out = new_result("latency", "Độ trễ (1 người dùng)")
    to = cfg["server"]["request_timeout_s"]
    n_warm = ctx.q("latency", "warmup")
    n_sample = ctx.q("latency", "sample_per_dataset")
    n_rep = ctx.q("latency", "repeat_queries")
    rep_gap = cfg["suites"]["latency"]["repeat_gap_s"]

    pool = []
    for ds in cfg["datasets"]:
        pool += load_golden(ds, ctx.root, n_sample, ctx.seed)
    if not pool:
        out["notes"].append("Không có câu hỏi nào để đo.")
        return out

    with ctx.monitor.phase("latency"):
        # 1) request đầu tiên – phản ánh chi phí khởi động nguội nếu server mới chạy
        first = stream_chat(ctx.base_url, new_session(), pool[0]["query"],
                            pool[0]["domain"], to)
        out["raw"]["first_request_s"] = first.total if first.ok else None

        # 2) warm-up (bỏ khỏi thống kê)
        for c in pool[1:1 + n_warm]:
            stream_chat(ctx.base_url, new_session(), c["query"], c["domain"], to)

        # 3) cache-miss: mỗi câu một session mới
        ttft, total, tps = [], [], []
        by_field = defaultdict(list)
        errors = 0
        for c in pool:
            r = stream_chat(ctx.base_url, new_session(), c["query"], c["domain"], to)
            if not r.ok:
                errors += 1
                continue
            total.append(r.total)
            ttft.append(r.ttft)
            by_field[(c["domain"], c["field"])].append(r.total)
            if r.n_chunks > 5 and r.total - (r.ttft or 0) > 0.05:
                tps.append(r.n_chunks / (r.total - r.ttft))

        # 4) cùng session + cùng câu hỏi lặp lại (kiểm tra cache)
        attempts = defaultdict(list)
        for c in pool[:n_rep]:
            sid = new_session()
            for k in (1, 2, 3):
                r = stream_chat(ctx.base_url, sid, c["query"], c["domain"], to)
                if r.ok:
                    attempts[k].append(r.total)
                time.sleep(rep_gap)  # để update_memory (nền) xong, cache key ổn định

    st, sp = summarize(total), summarize(ttft)
    fast = sum(1 for t in total if t < 1.0) / len(total) if total else None
    out["verdicts"] += [
        verdict("latency.ttft_p95", "TTFT p95 (cache-miss)", sp["p95"], "<=",
                slo["ttft_p95_max_s"], "s"),
        verdict("latency.total_p95", "Tổng thời gian p95 (cache-miss)", st["p95"],
                "<=", slo["total_p95_max_s"], "s"),
        verdict("latency.total_p50", "Tổng thời gian p50 (cache-miss)", st["p50"],
                "<=", slo["total_p50_max_s"], "s"),
        verdict("latency.repeat3_p95", "Lặp lại lần 3 cùng session p95",
                percentile(attempts[3], 95), "<=", slo["repeat_hit_p95_max_s"], "s",
                "đo hiệu quả cache"),
    ]
    out["tables"].append(table(
        f"Phân bố thời gian (n={st['n']}, lỗi={errors})",
        ["Chỉ số", "Mean", "p50", "p90", "p95", "p99", "Max"],
        [["TTFT (s)", sp["mean"], sp["p50"], sp["p90"], sp["p95"], sp["p99"], sp["max"]],
         ["Tổng (s)", st["mean"], st["p50"], st["p90"], st["p95"], st["p99"], st["max"]]]))
    rows = [[d, f, len(v), summarize(v)["p50"], summarize(v)["p95"]]
            for (d, f), v in sorted(by_field.items())]
    out["tables"].append(table("Tổng thời gian theo loại câu hỏi",
                               ["Domain", "Field", "n", "p50 (s)", "p95 (s)"], rows))
    out["tables"].append(table(
        "Tác động của cache (cùng session, cùng câu hỏi)",
        ["Lần hỏi", "n", "p50 (s)", "p95 (s)"],
        [[k, len(attempts[k]), percentile(attempts[k], 50), percentile(attempts[k], 95)]
         for k in (1, 2, 3)]))
    out["tables"].append(table("Thông số khác", ["Chỉ số", "Giá trị"], [
        ["Request đầu tiên (s)", out["raw"]["first_request_s"]],
        ["Tỉ lệ trả lời < 1s (fast path/cache)", fast],
        ["Tốc độ sinh ~ chunk/s (p50)", percentile(tps, 50)],
    ]))
    out["notes"].append(
        "'Chunk/s' xấp xỉ token/s khi server stream theo token. "
        "Request đầu tiên chỉ phản ánh khởi động nguội nếu bạn vừa bật server (hoặc dùng --launch).")
    return out
