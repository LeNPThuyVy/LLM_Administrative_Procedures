import os
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


MAX_QUERY_CHARS = max(1, int(os.getenv("MAX_QUERY_CHARS", "4000")))


class ChatRequest(BaseModel):
    session_id: str
    query: str = Field(max_length=MAX_QUERY_CHARS)
    domain: str | None = None

    @field_validator("session_id")
    @classmethod
    def session_id_must_be_uuid(cls, value: str) -> str:
        # Chuỗi tùy ý sẽ bị băm thành UUID cố định, khiến nhiều client
        # dùng chung một session.
        UUID(value)
        return value
