from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.schemas.chat import ChatRequest
from backend.services.chat_service import stream_chat_events
from domains import is_valid_domain, list_domains

router = APIRouter()


@router.get("/api/domains")
async def get_domains():
    return list_domains()


@router.post("/api/chat")
@router.post("/api/chat/stream")
async def chat(request: ChatRequest):
    if not is_valid_domain(request.domain):
        raise HTTPException(
            status_code=400,
            detail=f"Domain không hợp lệ: {request.domain}",
        )

    return StreamingResponse(
        stream_chat_events(request),
        media_type="text/event-stream",
    )
