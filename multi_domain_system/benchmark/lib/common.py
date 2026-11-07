"""Tiện ích dùng chung: nạp bộ câu hỏi, phân loại hành vi, đọc log, chạy server."""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from .sse_client import ChatResult, http_get_json, norm_text
from .stats import summarize


# ------------------------------------------------------------------ cases
def load_golden(ds: dict, root: Path, max_cases: int | None, seed: int) -> list[dict]:
    """Đọc golden set của một domain, chuẩn hoá về một dạng chung.

    Hỗ trợ 2 format đang có trong repo:
      {question, expected_document_id, expected_field, expected_keywords}
      {query, document_ids, expected_answer_keywords}
    """
    path = root / ds["golden"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for i, c in enumerate(raw):
        q = c.get("question") or c.get("query")
        if not q:
            continue
        docs = c.get("expected_document_id") or c.get("document_ids") or []
        if isinstance(docs, str):
            docs = [docs]
        cases.append({
            "id": c.get("id", f"{ds['domain']}_{i:03d}"),
            "domain": ds["domain"],
            "query": q,
            "expected_docs": docs,
            "field": c.get("expected_field") or "none",
            "keywords": c.get("expected_keywords")
            or c.get("expected_answer_keywords") or [],
        })
    if max_cases and len(cases) > max_cases:
        cases = random.Random(seed).sample(cases, max_cases)
        cases.sort(key=lambda x: x["id"])
    return cases


def load_scenarios(ds: dict, root: Path) -> list[dict]:
    p = ds.get("scenarios")
    if not p or not (root / p).exists():
        return []
    return json.loads((root / p).read_text(encoding="utf-8"))


def keyword_recall(answer: str, keywords: list[str]) -> float | None:
    if not keywords:
        return None
    a = norm_text(answer)
    return sum(1 for k in keywords if norm_text(k) in a) / len(keywords)


def classify_behavior(res: ChatResult, reject_markers: list[str]) -> str:
    """ANSWER / CLARIFY / REJECT / ERROR – suy ra từ phản hồi HTTP."""
    if not res.ok:
        return "ERROR"
    if res.needs_clarification:
        return "CLARIFY"
    a = norm_text(res.answer)
    if not a or any(norm_text(m) in a for m in reject_markers):
        return "REJECT"
    return "ANSWER"


def doc_match(expected, got: list[str]) -> bool:
    exp = [expected] if isinstance(expected, str) else list(expected or [])
    return any(e in got for e in exp)


# ------------------------------------------------------------------ log tail
_STAGE_RE = re.compile(r"\[time\]\s+(.+?)\s*=\s*([0-9.]+)s")


class LogTailer:
    """Đọc phần log MỚI của server và gom thời gian từng bước `[time] x = 0.12s`."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.pos = self.path.stat().st_size if self.path and self.path.exists() else 0

    def consume(self) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        if not self.path or not self.path.exists():
            return out
        with open(self.path, "rb") as f:
            f.seek(self.pos)
            data = f.read()
            self.pos = f.tell()
        for m in _STAGE_RE.finditer(data.decode("utf-8", "replace")):
            out.setdefault(m.group(1).strip(), []).append(float(m.group(2)))
        return out


def stage_rows(stages: dict[str, list[float]]) -> list[list]:
    rows = []
    for name, vals in sorted(stages.items(), key=lambda kv: -sum(kv[1])):
        s = summarize(vals)
        rows.append([name, s["n"], s["mean"], s["p50"], s["p95"], s["max"],
                     sum(vals)])
    return rows


# ------------------------------------------------------------------ launcher
def launch_server(cmd: str, cwd: Path, log_path: Path):
    curr_pp = os.environ.get("PYTHONPATH", "")
    new_pp = str(cwd) if not curr_pp else f"{cwd}{os.pathsep}{curr_pp}"
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONPATH=new_pp)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logf = open(log_path, "wb")
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, shell=True, cwd=str(cwd), env=env,
                            stdout=logf, stderr=subprocess.STDOUT, **kw)
    return proc, logf


def kill_tree(proc):
    try:
        import psutil
        parent = psutil.Process(proc.pid)
        kids = parent.children(recursive=True)
        for p in kids + [parent]:
            try:
                p.terminate()
            except Exception:
                pass
        psutil.wait_procs(kids + [parent], timeout=8)
        for p in kids + [parent]:
            try:
                if p.is_running():
                    p.kill()
            except Exception:
                pass
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def wait_health(base_url: str, timeout: float) -> float | None:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        st, _ = http_get_json(base_url, "/health", timeout=2)
        if st == 200:
            return time.perf_counter() - t0
        time.sleep(0.5)
    return None
