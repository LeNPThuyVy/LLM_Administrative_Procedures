
from sentence_transformers.cross_encoder import CrossEncoder

import my_config as cfg
from rag.retrieval import RetrievedChunk


_reranker: CrossEncoder | None = None


def rerank(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]::
    """
    def rerank(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(cfg.RERANKER_MODEL)
    return _reranker


def rerank(query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """
    Rerank retrieved chunks using a cross-encoder model.

    Unlike bi-encoder (embedding) retrieval, the cross-encoder receives
    the full (query, chunk) pair and produces a relevance score that is
    more accurate than cosine similarity alone.

    Each chunk's rerank_score is updated in-place, then chunks are
    returned sorted by rerank_score in descending order.
    """
    if not chunks:
        return chunks

    reranker = _get_reranker()

    pairs = [(query, chunk.content) for chunk in chunks]
    scores = reranker.predict(pairs).tolist()

    for chunk, score in zip(chunks, scores):
        chunk.rerank_score = float(score)

    return sorted(chunks, key=lambda c: c.rerank_score, reverse=True)
