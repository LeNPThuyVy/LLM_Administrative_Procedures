
from rag.retrieval import RetrievedChunk


def rerank(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """
    Placeholder reranking.

    Currently, reranking only sorts RetrievedChunk objects
    by retrieval_score in descending order.

    The chunks themselves are not modified.
    """
    return sorted(
        chunks,
        key=lambda chunk: chunk.retrieval_score,
        reverse=True,
    )

