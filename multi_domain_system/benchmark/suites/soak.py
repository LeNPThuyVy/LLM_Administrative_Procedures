"""Suite chạy dài (soak): phát hiện rò rỉ RAM và độ trễ trôi dần theo thời gian."""
from __future__ import annotations

import random
import threading
from collections import Counter
import time

from ..lib.common import load_golden
from ..lib.sse_client import new_session, stream_chat
from ..lib.stats import rate, summarize
from ..lib.verdict import new_result, table, verdict


def run(ctx) -> dict:
    cfg, slo = ctx.cfg, ctx.cfg["slo"]["soak"]
    sc = cfg["suites"]["soak"]
    out = new_result("soak", "Chạy dài (rò rỉ RAM / trôi độ trễ)")
    to = cfg["server"]["request_timeout_s"]
    duration = ctx.q("soak", "duration_s")
    conc = sc["concurrency"]

    pool = []
    for ds in cfg["datasets"]:
        pool += load_golden(ds, ctx.root, 30, ctx.seed)
    rnd = random.Random(ctx.seed)

    log: list[tuple[float, float, bool]] = []  # (t_tương_đối, tổng_thời_gian, ok)
    lock = threading.Lock()
    errs: Counter = Counter()
    t_start = time.perf_counter()
    deadline = t_start + duration
    stop = threading.Event()

    def worker(i: int):
        wr = random.Random(ctx.seed + i)
        sid = new_session()
        while time.perf_counter() < deadline and not stop.is_set():
            if wr.random() > sc["session_reuse_ratio"]:
                sid = new_session()
            c = wr.choice(pool)
            r = stream_chat(ctx.base_url, sid, c["query"], c["domain"], to)
            with lock:
                log.append((time.perf_counter() - t_start, r.total, r.ok))
                if not r.ok:
                    errs[f"{r.status}: {(r.error or '')[:60]}"] += 1
                recent = log[-20:]
                if len(log) >= 20 and sum(not x[2] for x in recent) >= 18:
                    stop.set()  # server chết hẳn -> dừng sớm

    with ctx.monitor.phase("soak"):
        threads = [threading.Thread(target=worker, args=(i,), daemon=True)
                   for i in range(conc)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    oks = [x for x in log if x[2]]
    third = duration / 3
    first = [x[1] for x in oks if x[0] < third]
    last = [x[1] for x in oks if x[0] >= 2 * third]
    p95_first, p95_last = summarize(first)["p95"], summarize(last)["p95"]
    drift = (p95_last / p95_first) if p95_first and p95_last else None
    mon = ctx.monitor.summary("soak", skip_frac=0.2)
    err = rate(len(log) - len(oks), len(log))

    out["verdicts"] += [
        verdict("soak.error_rate", "Tỉ lệ lỗi khi chạy dài", err, "<=", slo["error_rate_max"]),
        verdict("soak.latency_drift", "p95 cuối / p95 đầu (độ trôi độ trễ)", drift, "<=",
                slo["latency_drift_max"], "x"),
    ]
    if mon:
        out["verdicts"] += [
            verdict("soak.api_rss_slope", "Tốc độ tăng RAM của API", mon["slope_api_mb_min"],
                    "<=", slo["api_rss_slope_max_mb_min"], " MB/phút", "bỏ 20% đầu (khởi động)"),
            verdict("soak.llm_rss_slope", "Tốc độ tăng RAM của llama-server",
                    mon["slope_llm_mb_min"], "<=", slo["llm_rss_slope_max_mb_min"], " MB/phút"),
        ]
        out["tables"].append(table("Tài nguyên khi chạy dài", ["Chỉ số", "Giá trị"], [
            ["RAM đầu → cuối (MB)", f"{mon['start_mb']:.0f} → {mon['end_mb']:.0f}"],
            ["RAM đỉnh tổng (MB)", mon["peak_mb"]],
            ["RAM đỉnh API / LLM (MB)", f"{mon['peak_api_mb']:.0f} / {mon['peak_llm_mb']:.0f}"],
            ["CPU TB / đỉnh (%)", f"{mon['cpu_avg']:.0f} / {mon['cpu_peak']:.0f}"],
            ["Số thread đỉnh", mon["threads_peak"]],
            ["GPU đỉnh (MB, toàn máy)", mon["gpu_peak_mb"]],
        ]))
    out["tables"].append(table("Thông số chạy", ["Chỉ số", "Giá trị"], [
        ["Thời lượng (s)", duration], ["Đồng thời", conc], ["Số request", len(log)],
        ["p95 phần đầu / phần cuối (s)", f"{p95_first or 0:.2f} / {p95_last or 0:.2f}"],
    ]))
    if errs:
        out["tables"].append(table("Loại lỗi khi chạy dài", ["Lỗi", "Số lần"], [[k, v] for k, v in errs.most_common(8)]))
    if stop.is_set():
        out["notes"].append("Soak dừng sớm: gần như mọi request cuối đều lỗi (server treo hoặc sập).")
    out["notes"].append(
        "Độ dốc RAM là hồi quy tuyến tính trên các mẫu RSS; thời lượng ngắn (<5 phút) "
        "cho kết quả nhiễu – nên chạy ≥ 15 phút trước khi kết luận có rò rỉ.")
    return out
