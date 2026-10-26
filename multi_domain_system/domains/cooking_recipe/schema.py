from typing import Optional
from pydantic import BaseModel, ConfigDict


class CookingRecipeDocument(BaseModel):
    """Schema tự động cho domain cooking_recipe."""
    model_config = ConfigDict(extra="allow")

    document_id: str
    title: str
    category: str = "chung"
    content: Optional[str] = None
    source_url: Optional[str] = None
    aliases: list[str] = []
