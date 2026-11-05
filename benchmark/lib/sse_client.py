from __future__ import annotations

import json
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class ChatResult:
    ok: bool = False
    status: int = 200
    timed_out: bool = False
    error: str | None = None
    answer: str = ""
    doc_ids: list[str] = field(default_factory=list)
    mode: str | None = None
    needs_clarification: bool = False
    ttft: float = 0.0
    total: float = 0.0
    tokens_per_sec: float = 0.0


def new_session() -> str:
    """Tạo mới UUID session id."""
    return str(uuid.uuid4())


def norm_text(text: str) -> str:
    """Chuẩn hoá văn bản tiếng Việt để so sánh chuỗi."""
    if not text:
        return ""
    text = text.lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def http_get_json(url: str, timeout: float = 10.0) -> dict | None:
    """Gửi HTTP GET và giải mã JSON."""
    try:
        req = Request(url, headers={"User-Agent": "benchmark-agent"})
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except Exception:
        return None


def stream_chat(
    base_url: str,
    session_id: str,
    query: str,
    domain: str | None = None,
    timeout: float = 90.0,
) -> ChatResult:
    """
    Gửi request SSE tới /api/chat hoặc /api/chat/stream và ghi nhận các chỉ số:
    - ttft: thời gian từ khi gửi tới token đầu tiên
    - total: tổng thời gian request
    - answer, doc_ids, mode, needs_clarification
    """
    res = ChatResult()
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {"session_id": session_id, "query": query}
    if domain:
        payload["domain"] = domain

    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=body_bytes,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    t_start = time.perf_counter()
    tokens = []
    first_token_time = None

    try:
        with urlopen(req, timeout=timeout) as resp:
            current_event = "message"
            buffer = ""
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                lines = buffer.split("\n")
                buffer = lines.pop()

                for raw_line in lines:
                    line = raw_line.strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_str = line[5:].strip()
                        try:
                            val = json.loads(data_str)
                        except Exception:
                            continue

                        if current_event in ("chunk", "token"):
                            if first_token_time is None:
                                first_token_time = time.perf_counter()
                            tok = val.get("text", "")
                            if tok:
                                tokens.append(tok)
                        elif current_event == "evidence":
                            for ev in val.get("evidence_list", []):
                                doc_id = ev.get("document_id")
                                if doc_id and doc_id not in res.doc_ids:
                                    res.doc_ids.append(doc_id)
                        elif current_event == "done":
                            res.answer = val.get("answer", "")
                            res.needs_clarification = bool(val.get("needs_clarification"))
                            res.mode = val.get("mode")
                            for ev in val.get("evidence_list", []):
                                doc_id = ev.get("document_id")
                                if doc_id and doc_id not in res.doc_ids:
                                    res.doc_ids.append(doc_id)
                            res.ok = True

        t_end = time.perf_counter()
        res.total = max(0.001, t_end - t_start)
        res.ttft = (first_token_time - t_start) if first_token_time else res.total
        if not res.answer and tokens:
            res.answer = "".join(tokens)
        if len(tokens) > 1 and first_token_time:
            gen_time = max(0.001, t_end - first_token_time)
            res.tokens_per_sec = len(tokens) / gen_time

    except HTTPError as exc:
        res.ok = False
        res.status = exc.code
        res.error = f"HTTP {exc.code}: {exc.reason}"
        res.total = time.perf_counter() - t_start
    except TimeoutError as exc:
        res.ok = False
        res.timed_out = True
        res.error = f"Timeout: {exc}"
        res.total = time.perf_counter() - t_start
    except Exception as exc:
        res.ok = False
        res.error = str(exc)
        if "timed out" in str(exc).lower():
            res.timed_out = True
        res.total = time.perf_counter() - t_start

    return res
