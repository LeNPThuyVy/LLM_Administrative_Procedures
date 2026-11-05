from typing import Optional
from pydantic import BaseModel


class CuisineDocument(BaseModel):
    """
    Schema cho domain cuisine_demo (Khám phá Ẩm thực Việt Nam).
    """

    document_id: str
    title: str

    category: str = ""
    region: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    ingredients: Optional[str] = None
    price_range: Optional[str] = None
    famous_spots: Optional[str] = None
    address: Optional[str] = None
    source_url: Optional[str] = None
    content: Optional[str] = None
