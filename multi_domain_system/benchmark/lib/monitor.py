"""Đo RAM / CPU / GPU của server trong lúc benchmark chạy.

- Tự tìm process theo cổng đang LISTEN (vd 8000 = API, 8080 = llama-server)
  hoặc theo --pid, rồi gộp cả process con (llama-server do backend spawn).
- Lấy mẫu ở thread nền mỗi `interval` giây, gắn nhãn theo "phase".
- RAM là RSS (bộ nhớ vật lý process đang giữ). Lưu ý: model GGUF được mmap nên
  RSS của llama-server có thể tăng dần khi các trang được nạp thật sự.
"""
from __future__ import annotations

import contextlib
import shutil
import subprocess
import threading
import time

try:
    import psutil
except ImportError:  # vẫn chạy được, chỉ không có số liệu tài nguyên
    psutil = None

from .stats import linear_slope

MB = 1024 * 1024


def _label(proc) -> str:
    try:
        text = (proc.name() + " " + " ".join(proc.cmdline())).lower()
    except Exception:
        return "api"
    return "llm" if "llama" in text else "api"


class ResourceMonitor:
    def __init__(self, ports=(), pids=(), interval: float = 1.0,
                 gpu: bool = True):
        self.ports = set(ports)
        self.pids = set(pids)
        self.interval = interval
        self.samples: list[dict] = []
        self._phase = "idle"
        self._procs: dict[int, "psutil.Process"] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._nvsmi = shutil.which("nvidia-smi") if gpu else None
        self.available = psutil is not None
        self.found_any = False

    # ---------- tìm process ----------
    def add_pid(self, pid: int):
        self.pids.add(pid)

    def _roots(self) -> set[int]:
        roots = set(self.pids)
        if self.ports:
            try:
                for c in psutil.net_connections(kind="inet"):
                    if (c.status == psutil.CONN_LISTEN and c.laddr
                            and c.laddr.port in self.ports and c.pid):
                        roots.add(c.pid)
            except Exception:
                pass  # AccessDenied trên một số OS -> dùng --pid
        return roots

    def _refresh_procs(self):
        wanted: dict[int, "psutil.Process"] = {}
        for pid in self._roots():
            try:
                p = self._procs.get(pid) or psutil.Process(pid)
                wanted[pid] = p
                for ch in p.children(recursive=True):
                    wanted[ch.pid] = self._procs.get(ch.pid) or ch
            except Exception:
                continue
        self._procs = wanted

    # ---------- lấy mẫu ----------
    def _gpu(self):
        if not self._nvsmi:
            return None, None
        try:
            out = subprocess.run(
                [self._nvsmi, "--query-gpu=memory.used,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3).stdout
            mem = util = 0.0
            for line in out.strip().splitlines():
                m, u = [float(x) for x in line.split(",")]
                mem += m
                util = max(util, u)
            return mem, util
        except Exception:
            return None, None

    def sample_now(self) -> dict | None:
        if not self.available:
            return None
        self._refresh_procs()
        rss = {"api": 0.0, "llm": 0.0}
        cpu = 0.0
        threads = 0
        for p in list(self._procs.values()):
            try:
                rss[_label(p)] += p.memory_info().rss / MB
                cpu += p.cpu_percent(interval=None)
                threads += p.num_threads()
            except Exception:
                continue
        if self._procs:
            self.found_any = True
        gmem, gutil = self._gpu()
        s = {"t": time.time(), "phase": self._phase,
             "api_mb": rss["api"], "llm_mb": rss["llm"],
             "total_mb": rss["api"] + rss["llm"], "cpu": cpu,
             "threads": threads, "gpu_mb": gmem, "gpu_util": gutil,
             "sys_avail_mb": psutil.virtual_memory().available / MB,
             "n_procs": len(self._procs)}
        self.samples.append(s)
        return s

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.sample_now()
            except Exception:
                pass
            self._stop.wait(self.interval)

    def start(self):
        if not self.available:
            return
        self.sample_now()  # mồi cpu_percent
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    @contextlib.contextmanager
    def phase(self, name: str):
        prev, self._phase = self._phase, name
        try:
            yield
        finally:
            with contextlib.suppress(Exception):
                self.sample_now()
            self._phase = prev

    # ---------- tổng hợp ----------
    def summary(self, phase: str, skip_frac: float = 0.0) -> dict | None:
        ss = [s for s in self.samples if s["phase"] == phase]
        if not ss:
            return None
        body = ss[int(len(ss) * skip_frac):] or ss
        t0 = body[0]["t"]
        xs = [(s["t"] - t0) / 60.0 for s in body]  # phút

        def slope(key):
            return linear_slope(xs, [s[key] for s in body])

        gpu = [s["gpu_mb"] for s in ss if s["gpu_mb"] is not None]
        gutil = [s["gpu_util"] for s in ss if s["gpu_util"] is not None]
        return {
            "n_samples": len(ss),
            "start_mb": ss[0]["total_mb"], "end_mb": ss[-1]["total_mb"],
            "peak_mb": max(s["total_mb"] for s in ss),
            "avg_mb": sum(s["total_mb"] for s in ss) / len(ss),
            "peak_api_mb": max(s["api_mb"] for s in ss),
            "peak_llm_mb": max(s["llm_mb"] for s in ss),
            "cpu_avg": sum(s["cpu"] for s in ss) / len(ss),
            "cpu_peak": max(s["cpu"] for s in ss),
            "threads_peak": max(s["threads"] for s in ss),
            "gpu_peak_mb": max(gpu) if gpu else None,
            "gpu_util_peak": max(gutil) if gutil else None,
            "min_sys_avail_mb": min(s["sys_avail_mb"] for s in ss),
            "slope_total_mb_min": slope("total_mb"),
            "slope_api_mb_min": slope("api_mb"),
            "slope_llm_mb_min": slope("llm_mb"),
        }

    def overall_peak(self) -> dict | None:
        if not self.samples:
            return None
        return {
            "peak_total_mb": max(s["total_mb"] for s in self.samples),
            "peak_api_mb": max(s["api_mb"] for s in self.samples),
            "peak_llm_mb": max(s["llm_mb"] for s in self.samples),
        }
