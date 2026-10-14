from dataclasses import dataclass

@dataclass
class SubQuery:
    raw_mention: str            # đoạn người dùng nhắc tới thủ tục
    procedure_hint: str | None  # tên chuẩn nếu khớp title index
    fields: list[str]           # ["required_documents", "fee", ...]; rỗng = tổng quát
    order: int                  # thứ tự trong câu hỏi gốc

@dataclass
class SubResult:
    sub_query: SubQuery
    status: str                 # "FOUND" | "AMBIGUOUS" | "NOT_FOUND"
    document_id: str | None
    chunks: list                # RetrievedChunk, rỗng nếu không FOUND
    suggested_title: str | None
    score: float
