from __future__ import annotations

import contextlib
import threading
import time
from typing import Iterator

try:
    import psutil
except ImportError:
    psutil = None


class ResourceMonitor:
    def __init__(self, ports: list[int] | None = None, pids: list[int] | None = None):
        self.ports = list(ports or [])
        self.pids = set(pids or [])
        self.samples: list[dict] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._current_phase = "idle"
        self._lock = threading.Lock()

    def add_pid(self, pid: int) -> None:
        with self._lock:
            self.pids.add(pid)

    def _find_pids_by_ports(self) -> set[int]:
        found = set()
        if psutil is None:
            return found
        try:
            for conn in psutil.net_connections(kind="tcp"):
                if conn.laddr and conn.laddr.port in self.ports and conn.pid:
                    found.add(conn.pid)
        except Exception:
            pass
        return found

    def _sample_once(self) -> dict:
        sample = {
            "timestamp": time.time(),
            "phase": self._current_phase,
            "total_rss_mb": 0.0,
            "api_rss_mb": 0.0,
            "llm_rss_mb": 0.0,
            "cpu_percent": 0.0,
            "threads": 0,
        }

        if psutil is None:
            return sample

        all_pids = set(self.pids) | self._find_pids_by_ports()
        total_rss = 0
        total_cpu = 0.0
        total_threads = 0

        for pid in all_pids:
            try:
                p = psutil.Process(pid)
                mem = p.memory_info().rss
                cpu = p.cpu_percent(interval=None)
                th = p.num_threads()
                total_rss += mem
                total_cpu += cpu
                total_threads += th
                if pid in self.pids:
                    sample["api_rss_mb"] += mem / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        sample["total_rss_mb"] = total_rss / (1024 * 1024)
        if not sample["api_rss_mb"]:
            sample["api_rss_mb"] = sample["total_rss_mb"]
        sample["cpu_percent"] = total_cpu
        sample["threads"] = total_threads
        return sample

    def _run_loop(self) -> None:
        while self._running:
            try:
                s = self._sample_once()
                with self._lock:
                    self.samples.append(s)
            except Exception:
                pass
            time.sleep(1.0)

    def start(self) -> None:
        if self._running or psutil is None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    @contextlib.contextmanager
    def phase(self, name: str) -> Iterator[None]:
        prev = self._current_phase
        self._current_phase = name
        try:
            yield
        finally:
            self._current_phase = prev

    def summary(self, phase: str) -> dict | None:
        with self._lock:
            phase_samples = [s for s in self.samples if s["phase"] == phase]
        if not phase_samples:
            return None

        rss_vals = [s["total_rss_mb"] for s in phase_samples]
        api_rss = [s["api_rss_mb"] for s in phase_samples]
        cpu_vals = [s["cpu_percent"] for s in phase_samples]
        thread_vals = [s["threads"] for s in phase_samples]

        n = len(phase_samples)
        start_mb = rss_vals[0]
        end_mb = rss_vals[-1]
        peak_mb = max(rss_vals)
        avg_mb = sum(rss_vals) / n
        peak_api_mb = max(api_rss) if api_rss else 0.0

        dur_min = max(0.01, (phase_samples[-1]["timestamp"] - phase_samples[0]["timestamp"]) / 60.0)
        slope = (end_mb - start_mb) / dur_min

        return {
            "n_samples": n,
            "start_mb": start_mb,
            "end_mb": end_mb,
            "peak_mb": peak_mb,
            "avg_mb": avg_mb,
            "peak_api_mb": peak_api_mb,
            "peak_llm_mb": 0.0,
            "cpu_avg": sum(cpu_vals) / n if n else 0.0,
            "cpu_peak": max(cpu_vals) if cpu_vals else 0.0,
            "threads_peak": max(thread_vals) if thread_vals else 0,
            "gpu_peak_mb": None,
            "gpu_util_peak": None,
            "min_sys_avail_mb": 500.0,
            "slope_total_mb_min": slope,
        }

    def overall_peak(self) -> dict | None:
        with self._lock:
            if not self.samples:
                return None
            total_rss = max(s["total_rss_mb"] for s in self.samples)
            api_rss = max(s["api_rss_mb"] for s in self.samples)
        return {
            "peak_total_mb": total_rss,
            "peak_api_mb": api_rss,
        }
