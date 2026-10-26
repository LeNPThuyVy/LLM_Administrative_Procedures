"""
Unified FastAPI + Gradio server.

Endpoints:
  GET  /health                        → health check
  GET  /api/session/bootstrap         → tạo/lấy anonymous session_id (cookie)
  WS   /ws/chat                       → WebSocket chat (dùng session_id cookie)
  GET  /api/sessions/{id}/messages    → lịch sử tin nhắn của 1 session
  /    (root + all paths under /)     → Gradio Web UI


Run with:
    python backend/main.py
or:
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
"""

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import os
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

_root_dir = str(Path(__file__).resolve().parent.parent)
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)

import subprocess
import socket
import time
import asyncio
from contextlib import asynccontextmanager
import my_config

from backend.api.sessions import router as sessions_router
from backend.api.socket import router as socket_router
from backend.api.chat import router as chat_router
from backend.api.ingestion import router as ingestion_router

llama_process_3b = None
llama_process_1_5b = None

_system_ready_status = {
    "db": False,
    "embedding": False,
    "vector_store": False,
    "llm_3b": False,
    "llm_1_5b": False,
}

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

async def _warmup_background():
    # 1. Preload Database tables
    try:
        from context.init_db import init_db
        await init_db()
        _system_ready_status["db"] = True
        print("[startup] Đã khởi tạo cấu trúc Database thành công.")
    except Exception as e:
        print(f"[startup] Cảnh báo lỗi init_db: {e}")

    # 2. Preload Embedding Model, Vector Store, và Alias Catalog
    try:
        from rag.retrieval import load_embedding_model, load_vector_store, _get_alias_catalog, encode_query
        print("[startup] Đang nạp embedding model vào bộ nhớ...")
        await asyncio.to_thread(load_embedding_model)
        _system_ready_status["embedding"] = True

        print("[startup] Đang kết nối Qdrant vector store...")
        await asyncio.to_thread(load_vector_store)
        _system_ready_status["vector_store"] = True

        print("[startup] Đang nạp danh mục alias...")
        for d in ["administrative_procedures", "tourism_demo"]:
            await asyncio.to_thread(_get_alias_catalog, d)

        # Warmup encode 1 câu truy vấn để PyTorch cấp phát tensor tính toán
        print("[startup] Đang thực hiện warmup inference cho embedding model (BGE-M3)...")
        await asyncio.to_thread(encode_query, "thủ tục hành chính đăng ký kết hôn")
        print("[startup] Hoàn tất nạp và làm nóng tài nguyên Retrieval.")
    except Exception as e:
        print(f"[startup] Cảnh báo lỗi nạp tài nguyên RAG: {e}")


def _start_llama_server(port: int, model_path: Path, ctx_size: int, threads: int, log_name: str):
    """Khởi động tiến trình llama-server nền cho một model cụ thể."""
    if is_port_in_use(port):
        print(f"Port {port} đang được sử dụng. Bỏ qua khởi động llama-server.")
        return None

    if not model_path.exists():
        print(f"CẢNH BÁO: Không tìm thấy model tại {model_path}. Bỏ qua khởi động port {port}.")
        return None

    print(f"Khởi động llama-server tại port {port} (model: {model_path.name}, threads: {threads})...")
    cmd = [
        "llama-server",
        "-m", str(model_path),
        "--port", str(port),
        "--ctx-size", str(ctx_size),
        "--parallel", str(my_config.LLAMA_PARALLEL),
        "--threads", str(threads),
        "--threads-batch", str(threads),
        "--batch-size", str(my_config.LLAMA_BATCH_SIZE),
        "--ubatch-size", str(my_config.LLAMA_UBATCH_SIZE),
        "--flash-attn", "auto",
        "--cache-reuse", "256",
    ]
    os.makedirs("task", exist_ok=True)
    log_file = open(f"task/{log_name}", "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
    return proc


def _warmup_llama_instance(port: int, status_key: str, warmup_prompt: str = "Xin chào"):
    """Thực hiện request kiểm tra và warmup llama-server sau khi mở port."""
    import urllib.request
    import json
    import time

    time.sleep(1)
    # Chờ server báo health OK
    for _ in range(30):
        try:
            h_url = f"http://127.0.0.1:{port}/health"
            with urllib.request.urlopen(h_url, timeout=2) as h_resp:
                if json.loads(h_resp.read().decode("utf-8")).get("status") == "ok":
                    break
        except Exception:
            pass
        time.sleep(1)

    # Gửi dummy completion để nạp weights vào bộ nhớ đệm
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({
                "messages": [{"role": "user", "content": warmup_prompt}],
                "max_tokens": 1
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as _:
            pass
        _system_ready_status[status_key] = True
        print(f"[warmup] Llama-server tại port {port} ({status_key}) đã hoàn tất nạp bộ nhớ!")
    except Exception as err:
        print(f"[warmup] Bỏ qua warmup port {port}: {err}")
        _system_ready_status[status_key] = True  # Coi như sẵn sàng nếu port đã mở


@asynccontextmanager
async def lifespan(app: FastAPI):
    global llama_process_3b, llama_process_1_5b

    # Khởi động tác vụ preload ngầm cho DB, Embedding BGE-M3, Qdrant
    asyncio.create_task(_warmup_background())

    # Khởi động LLM 3B (Main RAG - Port 8080)
    port_3b = 8080
    llama_process_3b = _start_llama_server(
        port=port_3b,
        model_path=my_config.MODEL_3B_PATH,
        ctx_size=my_config.LLAMA_CTX_SIZE,
        threads=my_config.LLAMA_THREADS,
        log_name="llama_server_3b.log",
    )
    asyncio.create_task(asyncio.to_thread(_warmup_llama_instance, port_3b, "llm_3b", "Xin chào"))

    # Khởi động LLM 1.5B (Synthesizer / Clarification - Port 8081)
    port_1_5b = 8081
    synth_threads = max(2, my_config.LLAMA_THREADS // 2) if my_config.LLAMA_THREADS > 2 else 2
    llama_process_1_5b = _start_llama_server(
        port=port_1_5b,
        model_path=my_config.MODEL_1_5B_PATH,
        ctx_size=2048,
        threads=synth_threads,
        log_name="llama_server_1_5b.log",
    )
    asyncio.create_task(asyncio.to_thread(_warmup_llama_instance, port_1_5b, "llm_1_5b", "Làm rõ câu hỏi"))

    yield

    # Cleanup tiến trình khi tắt server
    for proc, name in [(llama_process_3b, "3B (8080)"), (llama_process_1_5b, "1.5B (8081)")]:
        if proc:
            print(f"Đang tắt llama-server {name}...")
            try:
                proc.terminate()
                proc.wait(timeout=5)
                print(f"Đã dọn dẹp llama-server {name}.")
            except Exception as e:
                print(f"Lỗi khi dọn dẹp llama-server {name}: {e}")

app = FastAPI(
    title="RAG Backend API",
    version="1.0.0",
    lifespan=lifespan
)

# --- REST / WebSocket routes ---
app.include_router(sessions_router)
app.include_router(socket_router)
app.include_router(chat_router)
app.include_router(ingestion_router)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api/system/status")
async def get_system_status():
    all_ready = all(_system_ready_status.values())
    return {
        "status": "ready" if all_ready else "warming_up",
        "all_ready": all_ready,
        "details": _system_ready_status,
    }

# --- Static files and Web UI ---
BASE_DIR = Path(__file__).resolve().parent.parent

# Serve static files from ui/static
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "ui" / "static")), name="static")

@app.get("/")
async def get_index():
    return FileResponse(str(BASE_DIR / "ui" / "web_ui.html"))


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=my_config.SERVER_HOST,
        port=my_config.SERVER_PORT,
        reload=False,
    )