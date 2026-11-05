from __future__ import annotations

import json
import random
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


class LogTailer:
    def __init__(self, log_path: Path | str):
        self.path = Path(log_path)
        self.last_pos = 0

    def consume(self) -> dict[str, list[float]]:
        stages: dict[str, list[float]] = {}
        if not self.path.exists():
            return stages

        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self.last_pos)
                lines = f.readlines()
                self.last_pos = f.tell()

            time_pattern = re.compile(r"\[time\]\s+([\w_]+)\s*=\s*([\d\.]+)s")
            for line in lines:
                m = time_pattern.search(line)
                if m:
                    stage, dur = m.group(1), float(m.group(2))
                    stages.setdefault(stage, []).append(dur)
        except Exception:
            pass
        return stages


def stage_rows(stages: dict[str, list[float]]) -> list[list[Any]]:
    rows = []
    for stage, times in sorted(stages.items()):
        if not times:
            continue
        n = len(times)
        s_times = sorted(times)
        mean_val = sum(times) / n
        p50 = s_times[int(n * 0.5)]
        p95 = s_times[int(n * 0.95)] if n > 1 else s_times[-1]
        max_val = max(times)
        total_val = sum(times)
        rows.append([stage, n, round(mean_val, 3), round(p50, 3), round(p95, 3), round(max_val, 3), round(total_val, 3)])
    return rows


def kill_tree(proc: subprocess.Popen | Any) -> None:
    try:
        if hasattr(proc, "terminate"):
            proc.terminate()
            proc.wait(timeout=3)
    except Exception:
        try:
            if hasattr(proc, "kill"):
                proc.kill()
        except Exception:
            pass


def launch_server(cmd: str, cwd: Path, log_path: Path) -> tuple[subprocess.Popen, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        shell=True,
    )
    return proc, log_file


def wait_health(base_url: str, timeout: float = 10.0) -> float | None:
    url = f"{base_url.rstrip('/')}/health"
    start = time.perf_counter()
    deadline = start + timeout
    while time.perf_counter() < deadline:
        try:
            req = Request(url)
            with urlopen(req, timeout=1.5) as resp:
                data = resp.read().decode("utf-8")
                if json.loads(data).get("status") == "ok":
                    return time.perf_counter() - start
        except Exception:
            pass
        time.sleep(0.5)
    return None


def load_golden(ds: dict, root: Path, n_sample: int | None = None, seed: int = 42) -> list[dict]:
    p = root / ds["golden"]
    if not p.exists():
        return []

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []

    dom = ds.get("domain", "default")
    cases = []
    for idx, c in enumerate(raw):
        expected_docs = c.get("expected_document_id") or []
        if isinstance(expected_docs, str):
            expected_docs = [expected_docs]
        cases.append({
            "id": c.get("id") or f"{dom}_{idx}",
            "query": c.get("question") or "",
            "domain": dom,
            "field": c.get("expected_field", "general"),
            "expected_docs": expected_docs,
            "keywords": c.get("expected_keywords") or [],
        })

    if n_sample and len(cases) > n_sample:
        rnd = random.Random(seed)
        cases = rnd.sample(cases, n_sample)
    return cases


def load_scenarios(ds_or_path: Any, root: Path | None = None) -> list[dict]:
    if isinstance(ds_or_path, dict):
        p_val = ds_or_path.get("scenarios")
        if not p_val:
            return []
        p = (root / p_val) if root else Path(p_val)
    else:
        p = Path(ds_or_path)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def doc_match(expected_docs: list[str], actual_docs: list[str]) -> bool:
    if not expected_docs:
        return True
    exp_set = {d.strip().lower() for d in expected_docs if d}
    act_set = {d.strip().lower() for d in actual_docs if d}
    return bool(exp_set & act_set)


def keyword_recall(answer: str, keywords: list[str]) -> float | None:
    if not keywords:
        return None
    if not answer:
        return 0.0
    ans_lower = answer.lower()
    hits = sum(1 for kw in keywords if kw.lower() in ans_lower)
    return hits / len(keywords)


def classify_behavior(r_or_text: Any, markers: list[str]) -> str:
    if hasattr(r_or_text, "answer"):
        if getattr(r_or_text, "needs_clarification", False):
            return "CLARIFY"
        text = r_or_text.answer
    else:
        text = str(r_or_text or "")
    if not text:
        return "REJECT"
    ans_lower = text.lower()
    for m in markers:
        if m.lower() in ans_lower:
            return "REJECT"
    return "ANSWER"
