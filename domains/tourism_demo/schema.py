from typing import Optional

from pydantic import BaseModel


class TourismDocument(BaseModel):
    """
    Schema cho domain tourism_demo.
    """

    document_id: str
    title: str

    category: str = ""
    location: Optional[str] = None
    description: Optional[str] = None
    price: Optional[str] = None
    opening_hours: Optional[str] = None
    address: Optional[str] = None
    source_url: Optional[str] = None
    content: Optional[str] = None
