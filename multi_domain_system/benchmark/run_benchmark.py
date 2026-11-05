"""Chạy benchmark toàn hệ thống.

Chạy từ thư mục gốc dự án:
    python -m benchmark.run_benchmark --quick
    python -m benchmark.run_benchmark --full --tag truoc_toi_uu
    python -m benchmark.run_benchmark --compare benchmark/results/bench_truoc_toi_uu.json
Xem benchmark/README.md để biết đầy đủ tuỳ chọn.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import yaml

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .lib import report
from .lib.common import (LogTailer, kill_tree, launch_server, stage_rows,
                         wait_health)
from .lib.monitor import ResourceMonitor, psutil
from .lib.sse_client import http_get_json, new_session, stream_chat
from .lib.verdict import new_result, table, verdict
from .suites import latency, load, quality, rules, soak

SUITES = {"quality": quality, "rules": rules, "latency": latency,
          "load": load, "soak": soak}
DEFAULT_SUITES = ["quality", "rules", "latency", "load"]
ORDER = ["quality", "rules", "latency", "load", "soak"]


def env_info() -> dict:
    info = {"Hệ điều hành": platform.platform(), "Python": platform.python_version()}
    if psutil:
        info["CPU (vật lý/logic)"] = f"{psutil.cpu_count(logical=False)}/{psutil.cpu_count()}"
        info["RAM máy (GB)"] = round(psutil.virtual_memory().total / 2**30, 1)
    nv = shutil.which("nvidia-smi")
    if nv:
        try:
            info["GPU"] = subprocess.run(
                [nv, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=3).stdout.strip().replace("\n", "; ")
        except Exception:
            pass
    info.setdefault("GPU", "không phát hiện (nvidia-smi)")
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(prog="benchmark")
    ap.add_argument("--base-url")
    ap.add_argument("--config", default=None)
    ap.add_argument("--suites", help=f"danh sách, cách nhau dấu phẩy: {','.join(ORDER)}")
    ap.add_argument("--full", action="store_true", help="chạy thêm soak test")
    ap.add_argument("--quick", action="store_true", help="bộ nhỏ, chạy vài phút")
    ap.add_argument("--tag", default=None, help="tên lần chạy (dùng cho tên file)")
    ap.add_argument("--compare", help="file JSON của lần chạy trước để so sánh")
    ap.add_argument("--pid", type=int, action="append", default=[],
                    help="PID server cần đo RAM (lặp lại được)")
    ap.add_argument("--watch-port", type=int, action="append", default=[])
    ap.add_argument("--launch", help='lệnh khởi động server, vd: "python -m uvicorn backend.main:app --port 8000"')
    ap.add_argument("--server-log", help="file log server để phân rã thời gian từng bước")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-fail-exit", action="store_true")
    a = ap.parse_args(argv)

    bench_dir = Path(__file__).resolve().parent
    root = bench_dir.parent
    cfg = yaml.safe_load(Path(a.config or bench_dir / "config.yaml").read_text(encoding="utf-8"))
    base_url = (a.base_url or cfg["server"]["base_url"]).rstrip("/")
    tag = a.tag or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(a.out_dir) if a.out_dir else bench_dir / "results"

    names = [s.strip() for s in a.suites.split(",")] if a.suites else list(DEFAULT_SUITES)
    if a.full and "soak" not in names:
        names.append("soak")
    names = [n for n in ORDER if n in names]

    def q(suite, key):
        if a.quick and key in cfg.get("quick", {}).get(suite, {}):
            return cfg["quick"][suite][key]
        return cfg["suites"][suite][key]

    ports = a.watch_port or cfg["server"]["watch_ports"]
    monitor = ResourceMonitor(ports=ports, pids=a.pid)
    ctx = SimpleNamespace(base_url=base_url, cfg=cfg, root=root, monitor=monitor,
                          quick=a.quick, seed=a.seed, q=q)

    # ---- khởi động server (tuỳ chọn) ----
    proc = logf = None
    log_path = Path(a.server_log) if a.server_log else None
    startup = None
    t_begin = time.time()
    if a.launch:
        log_path = log_path or (out_dir / f"server_{tag}.log")
        print(f"[bench] Khởi động server: {a.launch}")
        t_launch = time.perf_counter()
        proc, logf = launch_server(a.launch, root, log_path)
        monitor.add_pid(proc.pid)
        monitor.start()
        with monitor.phase("startup"):
            t_health = wait_health(base_url, 240)
            r = stream_chat(base_url, new_session(), "xin chào", None, 240) if t_health else None
            t_first = (time.perf_counter() - t_launch) if r and r.ok else None
            time.sleep(5)
        s = monitor.summary("startup")
        startup = new_result("startup", "Khởi động nguội")
        startup["verdicts"].append(verdict("startup.health_s", "Thời gian tới khi /health sẵn sàng",
                                           t_health, "<=", 120, "s"))
        startup["tables"].append(table("Khởi động", ["Chỉ số", "Giá trị"], [
            ["Tới /health (s)", t_health], ["Tới câu trả lời đầu tiên (s)", t_first],
            ["RAM sau khởi động (MB)", s["end_mb"] if s else None],
            ["RAM đỉnh khởi động (MB)", s["peak_mb"] if s else None]]))
    else:
        monitor.start()

    if not wait_health(base_url, 10):
        monitor.stop()
        sys.exit(f"[bench] Không kết nối được {base_url}/health – hãy bật server hoặc dùng --launch.")
    if psutil is None:
        print("[bench] Thiếu psutil → không đo được RAM. Cài: pip install psutil")

    tailer = LogTailer(log_path) if log_path else None
    results = {"tag": tag, "quick": a.quick, "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "env": env_info(), "suites": [], "resources": {}}
    if startup:
        results["suites"].append(startup)
    if tailer:
        tailer.consume()  # bỏ phần log khởi động

    for n in names:
        print(f"[bench] ▶ {n} ...")
        t0 = time.perf_counter()
        res = SUITES[n].run(ctx)
        if tailer:
            st = tailer.consume()
            if st:
                res["tables"].append(table(
                    "Phân rã thời gian theo bước (từ log server, mọi request trong suite)",
                    ["Bước", "n", "TB (s)", "p50", "p95", "Max", "Tổng (s)"], stage_rows(st)))
        results["suites"].append(res)
        bad = sum(v["status"] == "FAIL" for v in res["verdicts"])
        print(f"[bench] ✔ {n} xong sau {time.perf_counter() - t0:.0f}s – {bad} chỉ số trượt")

    monitor.stop()
    phases = sorted({s["phase"] for s in monitor.samples} - {"idle"})
    for p in phases:
        sm = monitor.summary(p)
        if sm:
            results["resources"][p] = sm
    slo = cfg["slo"]["resource"]
    pk = monitor.overall_peak()
    if pk:
        res = new_result("resource", "Tài nguyên tổng thể")
        res["verdicts"] += [
            verdict("resource.peak_total_mb", "RAM đỉnh toàn hệ thống (API + LLM)",
                    pk["peak_total_mb"], "<=", slo["total_rss_peak_max_mb"], " MB"),
            verdict("resource.peak_api_mb", "RAM đỉnh process API", pk["peak_api_mb"],
                    "<=", slo["api_rss_peak_max_mb"], " MB"),
        ]
        results["suites"].append(res)

    results["duration_s"] = time.time() - t_begin
    md = report.render(results)
    if a.compare:
        try:
            md += "\n" + report.compare(json.loads(Path(a.compare).read_text(encoding="utf-8")), results)
        except Exception as e:
            md += f"\n> Không so sánh được: {e}\n"
    jp, mp = report.save(results, out_dir, md)

    if proc:
        kill_tree(proc)
        logf.close()
    fails = [v for v in report.all_verdicts(results) if v["status"] == "FAIL"]
    print(f"\n[bench] Báo cáo: {mp}\n[bench] Dữ liệu : {jp}")
    print(f"[bench] {len(fails)} chỉ số trượt" + ("".join(f"\n   ❌ {v['label']}: {v['value']}" for v in fails)))
    if fails and not a.no_fail_exit:
        sys.exit(1)


if __name__ == "__main__":
    main()
