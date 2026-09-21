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

        # rerank_score is now a proper field on RetrievedChunk.
        rerank_score = chunk.rerank_score

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