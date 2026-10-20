
import re
from rag.retrieval import RetrievedChunk


def _compute_ngram_bonus(query: str, content: str, title: str = "") -> float:
    """
    Lightweight N-gram & exact phrase match score.
    Runs in < 2ms without extra RAM.
    Focuses on chunk content to differentiate chunks belonging to the same document.
    """
    if not query or not content:
        return 0.0

    # Extract meaningful tokens (length >= 2)
    q_tokens = [w for w in re.findall(r"\w+", query.lower(), flags=re.UNICODE) if len(w) > 1]
    if len(q_tokens) < 2:
        return 0.0

    content_lower = content.lower()
    bonus = 0.0

    # Content bigram exact match bonus (+0.04 each)
    for i in range(len(q_tokens) - 1):
        bg = f"{q_tokens[i]} {q_tokens[i + 1]}"
        if bg in content_lower:
            bonus += 0.04

    # Content trigram exact match bonus (+0.06 each)
    for i in range(len(q_tokens) - 2):
        tg = f"{q_tokens[i]} {q_tokens[i + 1]} {q_tokens[i + 2]}"
        if tg in content_lower:
            bonus += 0.06

    return min(bonus, 0.35)


def rerank(
    chunks: list[RetrievedChunk],
    query: str | None = None,
) -> list[RetrievedChunk]:
    """
    Lightweight Lexical & N-gram Reranker.
    Refines ranking by checking continuous n-gram and phrase overlap
    between query and chunk text without heavy neural cross-encoder overhead.
    """
    if not chunks:
        return []

    if not query or not query.strip():
        return sorted(
            chunks,
            key=lambda chunk: chunk.retrieval_score,
            reverse=True,
        )

    return sorted(
        chunks,
        key=lambda chunk: chunk.retrieval_score + _compute_ngram_bonus(
            query=query,
            content=chunk.content,
            title=str((chunk.metadata or {}).get("title", "")),
        ),
        reverse=True,
    )


