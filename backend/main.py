"""
Unified FastAPI + Gradio server.

Endpoints:
  GET  /health          → health check
  POST /api/chat        → SSE streaming chat (RAG pipeline)
  GET  /api/sessions    → session management
  /    (root + all paths under /)  → Gradio Web UI

Run with:
    python backend/main.py
or:
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
"""

import uvicorn
import gradio as gr
from fastapi import FastAPI

from backend.api.chat import router as chat_router
from backend.api.sessions import router as sessions_router
from backend.api.socket import router as socket_router

app = FastAPI(
    title="RAG Backend API",
    version="1.0.0",
)

# --- REST / SSE routes ---
app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(socket_router)

@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Mount Gradio UI at root ---
# Imported here (after FastAPI is created) to avoid circular import issues
# with any module that imports from app.py at top level.
from app import create_app as _create_gradio_app  # noqa: E402

_gradio_demo = _create_gradio_app()
app = gr.mount_gradio_app(app, _gradio_demo, path="/ui")


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )