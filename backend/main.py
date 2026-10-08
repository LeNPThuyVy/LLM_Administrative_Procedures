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

import subprocess
import socket
import time
from contextlib import asynccontextmanager
import my_config

from backend.api.sessions import router as sessions_router
from backend.api.socket import router as socket_router
from backend.api.chat import router as chat_router

llama_process = None

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

@asynccontextmanager
async def lifespan(app: FastAPI):
    global llama_process
    port = 8080
    if not is_port_in_use(port):
        print(f"Bắt đầu khởi động llama-server tại port {port}...")
        cmd = [
            "llama-server", 
            "-m", str(my_config.MODEL_3B_PATH), 
            "--port", str(port), 
            "--ctx-size", "4096"
        ]
        llama_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )
        
        for _ in range(30):
            if is_port_in_use(port):
                print("Llama-server đã sẵn sàng!")
                break
            time.sleep(1)
        else:
            print("CẢNH BÁO: Không thể khởi động llama-server.")
    else:
        print(f"Port {port} đang được sử dụng. Bỏ qua khởi động llama-server.")

    yield

    if llama_process:
        print("Đang tắt llama-server...")
        llama_process.terminate()
        llama_process.wait(timeout=5)
        print("Đã dọn dẹp llama-server.")

app = FastAPI(
    title="RAG Backend API",
    version="1.0.0",
    lifespan=lifespan
)

# --- REST / WebSocket routes ---
app.include_router(sessions_router)
app.include_router(socket_router)
app.include_router(chat_router)

@app.get("/health")
async def health():
    return {"status": "ok"}

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