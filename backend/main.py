from fastapi import FastAPI

from backend.api.chat import router as chat_router
from backend.api.sessions import router as sessions_router


app = FastAPI(
    title="RAG Backend API",
    version="1.0.0"
)

app.include_router(chat_router)
app.include_router(sessions_router)


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }