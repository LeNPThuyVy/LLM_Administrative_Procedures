from dataclasses import dataclass

from rag.retrieval import RetrievedChunk


@dataclass
class EvidenceCandidate:
    candidate_id: str
    chunk_id: str
    document_id: str
    content: str
    title: str
    document_type: str
    page: int | None
    source_url: str | None
    retrieval_score: float
    rerank_score: float

    # C - MCP/tool evidence.
    # Default giữ tương thích với toàn bộ evidence RAG hiện tại.
    source: str = ""


def build_evidence_candidates(chunks: list[RetrievedChunk]) -> list[EvidenceCandidate]:
    """
    Convert retrieved chunks into evidence candidates.

    This function only prepares evidence candidates.
    It does not verify or judge the evidence.
    """

    candidates: list[EvidenceCandidate] = []

    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.metadata or {}

        page = metadata.get("page")
        if page is not None:
            page = int(page)

        source_url = metadata.get("source_url")
        if not source_url:
            source_url = None

        # RetrievedChunk currently does not have rerank_score.
        # For PoC, use retrieval_score as the rerank_score.
        rerank_score = getattr(
            chunk,
            "rerank_score",
            chunk.retrieval_score,
        )

        candidate = EvidenceCandidate(
            candidate_id=f"EC_{index:03d}",
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            content=chunk.content,
            title=str(metadata.get("title", "")),
            document_type=str(metadata.get("document_type", "")),
            page=page,
            source_url=source_url,
            retrieval_score=chunk.retrieval_score,
            rerank_score=rerank_score,
        )

        candidates.append(candidate)

    return candidates
def build_tool_evidence_candidate(
    *,
    index: int,
    tool_name: str,
    content: str,
    title: str = "",
    document_id: str = "",
    source_url: str | None = None,
) -> EvidenceCandidate:
    """
    Convert MCP tool output into an EvidenceCandidate.

    Tool evidence uses source="tool:<tool_name>" so downstream
    code can distinguish it from normal RAG evidence.
    """
    return EvidenceCandidate(
        candidate_id=f"EC_{900 + index:03d}",
        chunk_id=f"tool:{tool_name}:{index}",
        document_id=document_id,
        content=content,
        title=title or tool_name,
        document_type="tool",
        page=None,
        source_url=source_url,
        retrieval_score=1.0,
        rerank_score=1.0,
        source=f"tool:{tool_name}",
    )