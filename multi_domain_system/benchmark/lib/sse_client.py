"""Client SSE cho POST /api/chat – chỉ dùng thư viện chuẩn (http.client).

Dùng thread thay vì asyncio để chạy được ở mọi môi trường, không cần httpx.
"""
from __future__ import annotations

import http.client
import json
import socket
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class ChatResult:
    ok: bool = False                 # nhận được event `done`
    status: int | None = None
    error: str | None = None
    timed_out: bool = False
    ttft: float | None = None        # tới chunk đầu (hoặc event nội dung đầu tiên)
    total: float = 0.0
    answer: str = ""
    doc_ids: list = field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    mode: str | None = None          # chỉ có nếu server gửi `mode` trong event done
    n_chunks: int = 0
    events: list = field(default_factory=list)


def new_session() -> str:
    return str(uuid.uuid4())


def collect_doc_ids(obj, out: list | None = None) -> list:
    out = out if out is not None else []
    if isinstance(obj, dict):
        d = obj.get("document_id")
        if isinstance(d, str) and d not in out:
            out.append(d)
        for v in obj.values():
            collect_doc_ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_doc_ids(v, out)
    return out


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "").lower()
    return " ".join(s.split())


def _conn(base_url: str, timeout: float):
    u = urlparse(base_url)
    https = u.scheme == "https"
    cls = http.client.HTTPSConnection if https else http.client.HTTPConnection
    return cls(u.hostname, u.port or (443 if https else 80), timeout=timeout)


def stream_chat(base_url: str, session_id: str, query: str,
                domain: str | None = None, timeout: float = 90.0) -> ChatResult:
    res = ChatResult()
    t0 = time.perf_counter()
    conn = None
    try:
        conn = _conn(base_url, timeout)
        body = json.dumps({"session_id": session_id, "query": query,
                           "domain": domain}, ensure_ascii=False).encode("utf-8")
        conn.request("POST", "/api/chat", body=body, headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "text/event-stream"})
        resp = conn.getresponse()
        res.status = resp.status
        if resp.status != 200:
            res.error = f"HTTP {resp.status}: " + \
                resp.read(300).decode("utf-8", "replace")
            return res

        event = None
        chunks: list[str] = []
        sections: list[str] = []
        done = None
        while True:
            raw = resp.readline()          # socket timeout = im lặng quá `timeout`
            if not raw:
                break
            now = time.perf_counter()
            if now - t0 > timeout:         # trần tổng thời gian
                raise socket.timeout("overall timeout")
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except ValueError:
                    data = None
                res.events.append(event)
                if event == "chunk":
                    if res.ttft is None:
                        res.ttft = now - t0
                    res.n_chunks += 1
                    if isinstance(data, dict):
                        chunks.append(data.get("text", ""))
                elif event in ("evidence", "section", "clarification"):
                    if res.ttft is None:
                        res.ttft = now - t0
                    collect_doc_ids(data, res.doc_ids)
                    if event == "section" and isinstance(data, dict):
                        sections.append(str(data.get("text", "")))
                    if event == "clarification" and isinstance(data, dict):
                        res.needs_clarification = True
                        res.clarification_question = data.get("question")
                elif event == "done":
                    done = data if isinstance(data, dict) else {}
                    collect_doc_ids(done, res.doc_ids)
            elif line == "":
                event = None

        if done is None:
            res.error = "stream kết thúc mà không có event `done`"
        else:
            res.ok = True
            res.answer = (done.get("answer") or "\n".join(sections)
                          or "".join(chunks))
            res.needs_clarification = bool(
                res.needs_clarification or done.get("needs_clarification"))
            res.mode = done.get("mode")
            if res.ttft is None:
                res.ttft = time.perf_counter() - t0
    except (socket.timeout, TimeoutError):
        res.timed_out = True
        res.error = "timeout"
    except (OSError, http.client.HTTPException) as e:
        res.error = f"{type(e).__name__}: {e}"
    finally:
        res.total = time.perf_counter() - t0
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return res


def http_get_json(base_url: str, path: str, timeout: float = 5.0):
    """Trả về (status, data). Lỗi mạng -> (None, 'mô tả lỗi')."""
    conn = None
    try:
        conn = _conn(base_url, timeout)
        conn.request("GET", path)
        r = conn.getresponse()
        raw = r.read().decode("utf-8", "replace")
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw
    except (OSError, http.client.HTTPException) as e:
        return None, f"{type(e).__name__}: {e}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
