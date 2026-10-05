from typing import Optional

from pydantic import BaseModel


class ProcedureDocument(BaseModel):
    """
    Schema cho domain administrative_procedures.

    Bám theo cấu trúc thực tế của data/procedures.json.
    """

    document_id: str
    title: str

    document_type: str = ""
    category: str = ""

    submission_method: Optional[str] = None
    required_documents: Optional[str] = None
    processing_time: Optional[str] = None
    fee: Optional[str] = None
    submission_location: Optional[str] = None
    notes: Optional[str] = None
    source_url: Optional[str] = None
    content: Optional[str] = None