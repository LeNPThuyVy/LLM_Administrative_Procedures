from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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


@dataclass
class ContextObject:
    session: Dict[str, Any] = field(default_factory=dict)
    user: Dict[str, Any] = field(default_factory=dict)

    conversation_summary: str = ""

    recent_messages: List[Dict[str, Any]] = field(
        default_factory=list
    )

    structured_context: Dict[str, Any] = field(
        default_factory=dict
    )

    long_term_memory: Dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class FinalResult:
    answer: str

    evidence_list: List[Dict[str, Any]] = field(
        default_factory=list
    )

    structured_context: Dict[str, Any] = field(
        default_factory=dict
    )