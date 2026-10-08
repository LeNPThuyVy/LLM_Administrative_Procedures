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
import asyncio
import socket
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
import uuid
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from backend.services.logging_service import log_event

import my_config
from context.database import engine
from rag.retrieval import load_vector_store

from backend.api.sessions import router as sessions_router
from backend.api.socket import router as socket_router
from backend.api.chat import router as chat_router

llama_process = None


def is_port_in_use(port: int) -> bool:
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as sock:
        return (
            sock.connect_ex(
                ("127.0.0.1", port)
            )
            == 0
        )


def is_llama_server_ready(
    port: int,
) -> bool:
    try:
        with urlopen(
            f"http://127.0.0.1:{port}/health",
            timeout=2,
        ) as response:
            return response.status == 200

    except (URLError, OSError):
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global llama_process

    port = 8080

    if not is_port_in_use(port):
        print(
            f"Bắt đầu khởi động llama-server "
            f"tại port {port}..."
        )

        cmd = [
            "llama-server",
            "-m",
            str(my_config.MODEL_3B_PATH),
            "--port",
            str(port),
            "--ctx-size",
            "4096",
        ]

        llama_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )

    else:
        print(
            f"Port {port} đang được sử dụng. "
            "Kiểm tra llama-server hiện có..."
        )

    # Port mở chưa đủ.
    # Chỉ coi LLM ready khi /health trả 200.
    for _ in range(60):
        if is_llama_server_ready(port):
            print(
                "Llama-server đã healthy "
                "và sẵn sàng!"
            )
            break

        await asyncio.sleep(1)

    else:
        print(
            "CẢNH BÁO: llama-server "
            "chưa healthy sau 60 giây."
        )

    yield

    if llama_process:
        print("Đang tắt llama-server...")

        llama_process.terminate()

        try:
            llama_process.wait(
                timeout=5
            )
        except subprocess.TimeoutExpired:
            llama_process.kill()

        print(
            "Đã dọn dẹp llama-server."
        )
async def check_database_health() -> dict:
    started = time.perf_counter()

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        return {
            "status": "ok",
            "latency_ms": round(
                (time.perf_counter() - started) * 1000,
                2,
            ),
        }

    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": round(
                (time.perf_counter() - started) * 1000,
                2,
            ),
            "error": type(exc).__name__,
        }


async def check_qdrant_health() -> dict:
    started = time.perf_counter()

    try:
        client = load_vector_store()

        await asyncio.to_thread(
            client.get_collections
        )

        return {
            "status": "ok",
            "latency_ms": round(
                (time.perf_counter() - started) * 1000,
                2,
            ),
        }

    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": round(
                (time.perf_counter() - started) * 1000,
                2,
            ),
            "error": type(exc).__name__,
        }


async def check_llm_health() -> dict:
    started = time.perf_counter()

    def ping_llama_server():
        with urlopen(
            "http://127.0.0.1:8080/health",
            timeout=3,
        ) as response:
            return response.status

    try:
        status_code = await asyncio.to_thread(
            ping_llama_server
        )

        if status_code != 200:
            raise RuntimeError(
                f"Unexpected status: "
                f"{status_code}"
            )

        return {
            "status": "ok",
            "latency_ms": round(
                (
                    time.perf_counter()
                    - started
                )
                * 1000,
                2,
            ),
        }

    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": round(
                (
                    time.perf_counter()
                    - started
                )
                * 1000,
                2,
            ),
            "error":
                type(exc).__name__,
        }
app = FastAPI(
    title="RAG Backend API",
    version="1.0.0",
    lifespan=lifespan
)
@app.middleware("http")
async def request_logging_middleware(
    request: Request,
    call_next,
):
    incoming_request_id = (
        request.headers.get("X-Request-ID", "")
        .strip()
    )

    request_id = (
        incoming_request_id[:128]
        if incoming_request_id
        else str(uuid.uuid4())
    )

    request.state.request_id = request_id

    started = time.perf_counter()

    try:
        response = await call_next(request)

    except Exception as exc:
        latency_ms = round(
            (
                time.perf_counter()
                - started
            )
            * 1000,
            2,
        )

        log_event(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=500,
            latency_ms=latency_ms,
            error=type(exc).__name__,
        )

        raise

    latency_ms = round(
        (
            time.perf_counter()
            - started
        )
        * 1000,
        2,
    )

    response.headers[
        "X-Request-ID"
    ] = request_id

    log_event(
        "http_request",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=latency_ms,
    )

    return response
allowed_origins = [
    origin.strip()
    for origin in my_config.ALLOWED_ORIGINS.split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
# --- REST / WebSocket routes ---
app.include_router(sessions_router)
app.include_router(socket_router)
app.include_router(chat_router)

@app.get("/health")
async def health():
    database, qdrant, llm = await asyncio.gather(
        check_database_health(),
        check_qdrant_health(),
        check_llm_health(),
    )

    dependencies = {
        "database": database,
        "qdrant": qdrant,
        "llm": llm,
    }

    overall_status = (
        "ok"
        if all(
            item["status"] == "ok"
            for item in dependencies.values()
        )
        else "degraded"
    )

    payload = {
        "status": overall_status,
        "dependencies": dependencies,
    }

    return JSONResponse(
        status_code=(
            200
            if overall_status == "ok"
            else 503
        ),
        content=payload,
    )

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
        host="127.0.0.1",
        port=8000,
        reload=False,
    )