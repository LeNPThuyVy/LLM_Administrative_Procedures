"""Server giả lập giao thức /api/chat (SSE) để tự kiểm tra bộ benchmark mà không cần model.

    python benchmark/selftest/mock_server.py --port 8765 [--buggy-semaphore] [--leak-mb 1]

--buggy-semaphore : acquire semaphore 2 lần như cấu trúc hiện tại của backend/api/chat.py
--leak-mb N       : mỗi request giữ lại N MB (để thử bộ phát hiện rò rỉ RAM)
--send-mode       : gửi `mode` trong event done
Đây KHÔNG phải server thật – chỉ dùng để kiểm tra chính benchmark.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
A = {}          # query -> (domain, doc_id, keywords)
LEAK = []
SESS_LOCKS: dict[str, threading.Lock] = {}
SEM = threading.Semaphore(3)
OPT = None
DISCLAIMER = "Đây là thông tin tư vấn tự động. Vui lòng liên hệ cơ quan nhà nước để được hỗ trợ chính xác nhất."


def load():
    for dom, p in [("administrative_procedures", "domains/administrative_procedures/golden_set.json"),
                   ("tourism_demo", "domains/tourism_demo/golden_set.json")]:
        for c in json.loads((ROOT / p).read_text(encoding="utf-8")):
            d = c.get("expected_document_id") or []
            d = [d] if isinstance(d, str) else d
            A[c["question"]] = (dom, d, c.get("expected_keywords", []))


def compute(domain, q):
    ql = q.lower()
    if "system prompt" in ql or "bỏ qua mọi quy tắc" in ql:
        return "Yêu cầu này không thể được xử lý vì vi phạm quy tắc an toàn.", [], False, "strict"
    if "hà nội" in ql:
        return "Hiện tại hệ thống chỉ hỗ trợ TP.HCM. Địa điểm bạn hỏi chưa có trong cơ sở dữ liệu.", [], False, "strict"
    if "visa" in ql:
        return "Xin lỗi, tôi chưa có thông tin chắc chắn về visa.", [], False, "strict"
    if q in A:
        dom, doc, kws = A[q]
        body = "Thông tin: " + ", ".join(kws) + ". Bạn cần gì thêm cứ hỏi mình nhé!"
        if dom == "administrative_procedures":
            body += "\n\n" + DISCLAIMER
        return body, list(doc), False, ("strict" if dom == "administrative_procedures" else "friendly")
    if "kết hôn" in ql and domain == "administrative_procedures":
        return "Hồ sơ kết hôn gồm tờ khai, CCCD... [EC_001]\n\n" + DISCLAIMER, ["PROC_004"], False, "strict"
    if "giá vé" in ql and "hạ long" in ql:
        return "Vé tuyến 1 là 290.000đ nhé bạn!", ["TD001"], False, "friendly"
    if domain == "tourism_demo":
        return "Xin lỗi bạn, mình chưa có thông tin về địa điểm này nhé!", [], False, "friendly"
    return "Tôi chưa có đủ thông tin để trả lời câu hỏi này.\n\n" + DISCLAIMER, [], False, "strict"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send(200, '{"status":"ok"}') if self.path == "/health" else self._send(404, "{}")

    def ev(self, name, data):
        self.wfile.write(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        q, sid, dom = req.get("query", ""), req.get("session_id", "x"), req.get("domain") or "administrative_procedures"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        lock = SESS_LOCKS.setdefault(sid, threading.Lock())
        with lock:
            SEM.acquire()
            try:
                time.sleep(0.05)    # tương đương `await get_context(...)` (DB) giữa 2 lần acquire
                if OPT.buggy:
                    SEM.acquire()   # <- bản sao cấu trúc lỗi: acquire lần 2
                try:
                    time.sleep(OPT.latency)
                    if OPT.leak_mb:
                        LEAK.append(b"x" * int(OPT.leak_mb * 1024 * 1024))
                    ans, docs, clar, mode = compute(dom, q)
                    print(f'[time] generate = {OPT.latency:.2f}s', flush=True)
                    print('[time] verify = 0.02s', flush=True)
                    for w in ans.split(" "):
                        self.ev("chunk", {"text": w + " "})
                        time.sleep(0.005)
                    cl = [{"claim": "c", "status": "ok", "reason": "",
                           "citations": [{"evidence_id": "EC_001", "document_id": d, "chunk_id": d + "_general",
                                          "title": "t", "source_url": None}]} for d in docs]
                    self.ev("evidence", {"evidence_list": cl})
                    done = {"answer": ans, "evidence_list": cl, "needs_clarification": clar}
                    if OPT.send_mode:
                        done["mode"] = mode
                    self.ev("done", done)
                finally:
                    if OPT.buggy:
                        SEM.release()
            finally:
                SEM.release()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--latency", type=float, default=0.3)
    ap.add_argument("--buggy-semaphore", dest="buggy", action="store_true")
    ap.add_argument("--leak-mb", type=float, default=0)
    ap.add_argument("--send-mode", action="store_true")
    OPT = ap.parse_args()
    load()
    ThreadingHTTPServer.daemon_threads = True
    print(f"mock server on :{OPT.port} buggy={OPT.buggy} leak={OPT.leak_mb}MB", flush=True)
    ThreadingHTTPServer(("127.0.0.1", OPT.port), H).serve_forever()
