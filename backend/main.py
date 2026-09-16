from fastapi import FastAPI

from api.chat import router as chat_router


app = FastAPI(
    title="RAG Backend API",
    version="1.0.0"
)

app.include_router(chat_router)


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }