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

from backend.api.sessions import router as sessions_router
from backend.api.socket import router as socket_router
from backend.api.chat import router as chat_router

app = FastAPI(
    title="RAG Backend API",
    version="1.0.0",
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