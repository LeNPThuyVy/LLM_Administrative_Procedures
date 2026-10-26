from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str
    query: str
    domain: str | None = None