from typing import Optional
from pydantic import BaseModel


class TourismDocument(BaseModel):
    """
    Schema cho domain tourism_demo (Du lịch Việt Nam).
    """

    document_id: str
    title: str

    category: str = ""
    location: Optional[str] = None
    description: Optional[str] = None
    highlights: Optional[str] = None
    best_time: Optional[str] = None
    ticket_price: Optional[str] = None
    address: Optional[str] = None
    source_url: Optional[str] = None
    content: Optional[str] = None
    aliases: list[str] = []
