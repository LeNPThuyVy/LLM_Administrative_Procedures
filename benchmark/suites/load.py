"""Suite tải: tăng dần số người dùng đồng thời, tìm điểm gãy, phát hiện treo/deadlock."""
from __future__ import annotations

import random
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from ..lib.common import load_golden
from ..lib.sse_client import new_session, stream_chat
from ..lib.stats import rate, summarize
from ..lib.verdict import new_result, table, verdict


def run(ctx) -> dict:
    cfg, slo = ctx.cfg, ctx.cfg["slo"]["load"]
    lc = cfg["suites"]["load"]
    out = new_result("load", "Chịu tải đồng thời")
    to = lc.get("request_timeout_s", cfg["server"]["request_timeout_s"])
    levels = ctx.q("load", "levels")
    per_worker = ctx.q("load", "requests_per_worker")
    target = min(lc["target_concurrency"], max(levels))  # --quick chỉ thử tới mức thấp hơn

    pool = []
    for ds in cfg["datasets"]:
        pool += load_golden(ds, ctx.root, 30, ctx.seed)
    rnd = random.Random(ctx.seed)

    rows, summary_by_level, breaking = [], {}, None
    with ctx.monitor.phase("load_all"):
        for lv in levels:
            n = max(lv * per_worker, lc["min_requests_per_level"])
            jobs = [rnd.choice(pool) for _ in range(n)]
            t0 = time.perf_counter()
            with ctx.monitor.phase(f"load_c{lv}"):
                with ThreadPoolExecutor(max_workers=lv) as ex:
                    results = list(ex.map(
                        lambda c: stream_chat(ctx.base_url, new_session(),
                                              c["query"], c["domain"], to), jobs))
            wall = time.perf_counter() - t0

            ok = [r for r in results if r.ok]
            timeouts = sum(r.timed_out for r in results)
            err_kinds = Counter((r.error or "")[:40] for r in results if not r.ok)
            tt, tp = summarize([r.total for r in ok]), summarize([r.ttft for r in ok])
            err_rate = rate(len(results) - len(ok), len(results))
            mon = ctx.monitor.summary(f"load_c{lv}") or {}
            summary_by_level[lv] = {"err": err_rate, "p95": tt["p95"], "ok": len(ok),
                                    "n": len(results), "timeouts": timeouts}
            rows.append([lv, len(results), 1 - err_rate, timeouts, tp["p50"], tp["p95"],
                         tt["p50"], tt["p95"], tt["p99"], len(ok) / wall,
                         mon.get("peak_mb"), mon.get("cpu_avg")])

            if err_rate >= lc["abort_error_rate"]:
                breaking = lv
                stalled = len(ok) == 0
                out["notes"].append(
                    f"Mức {lv} đồng thời: {err_rate:.0%} request lỗi"
                    + (" và KHÔNG request nào hoàn thành – nghi ngờ server bị treo/deadlock "
                       "(vd semaphore bị acquire lồng nhau trong chat.py)." if stalled else ".")
                    + f" Lỗi: {dict(err_kinds)}")
                # server có hồi phục sau khi ngừng tải không?
                time.sleep(lc["cooldown_s"])
                probe = stream_chat(ctx.base_url, new_session(), pool[0]["query"],
                                    pool[0]["domain"], to)
                out["raw"]["recovered_after_break"] = probe.ok
                out["notes"].append(
                    "Sau khi dừng tải, server " + ("ĐÃ hồi phục." if probe.ok
                                                   else "KHÔNG hồi phục (cần restart)."))
                break
            time.sleep(lc["cooldown_s"])

        # nhiều request cùng một session phải được xếp hàng, không lỗi
        sid, q = new_session(), pool[0]
        with ThreadPoolExecutor(max_workers=3) as ex:
            same = list(ex.map(lambda _: stream_chat(
                ctx.base_url, sid, q["query"], q["domain"], to), range(3)))
        same_ok = sum(r.ok for r in same)

    sustainable = [lv for lv, s in summary_by_level.items()
                   if s["err"] == 0 and s["p95"] is not None
                   and s["p95"] <= slo["total_p95_max_s"]]
    max_sust = max(sustainable) if sustainable else 0
    at_target = summary_by_level.get(target) or (
        summary_by_level[max(summary_by_level)] if summary_by_level else None)

    out["verdicts"] += [
        verdict("load.max_sustainable", "Số người dùng đồng thời tối đa đạt SLO",
                max_sust, ">=", target, "", "error=0 và p95 ≤ ngưỡng"),
        verdict("load.error_rate_at_target", f"Tỉ lệ lỗi ở mức ~{target} đồng thời",
                at_target["err"] if at_target else None, "<=", slo["error_rate_max"]),
        verdict("load.p95_at_target", f"p95 tổng thời gian ở mức ~{target} đồng thời",
                at_target["p95"] if at_target else None, "<=", slo["total_p95_max_s"], "s"),
        verdict("load.same_session", "3 request cùng session đều thành công",
                same_ok, ">=", 3),
    ]
    out["tables"].append(table(
        "Kết quả theo mức đồng thời",
        ["Đồng thời", "Số req", "Thành công", "Timeout", "TTFT p50", "TTFT p95",
         "Tổng p50", "Tổng p95", "Tổng p99", "Req/s", "RAM đỉnh (MB)", "CPU TB (%)"], rows))
    out["raw"]["levels"] = summary_by_level
    out["raw"]["breaking_level"] = breaking
    out["notes"].append(
        "CPU% là tổng trên mọi lõi (có thể > 100%). Req/s đếm request thành công / thời gian tường.")
    return out
