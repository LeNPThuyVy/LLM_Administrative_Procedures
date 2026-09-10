from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    content: str
    retrieval_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceCandidate:
    chunk_id: str
    document_id: str
    content: str
    retrieval_score: float
    rerank_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VerifiedEvidence:
    chunk_id: str
    document_id: str
    content: str
    verification_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class APIEvidence:
    source_id: str
    document_id: str
    title: str
    snippet: str
    page_number: Optional[int] = None