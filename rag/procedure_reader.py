"""
Lightweight retrieval for procedure/topic hints fed to the synthesizer.

Issue #2 fix: chunks below MIN_RETRIEVAL_SCORE are filtered out so that
the synthesizer receives no hints (returns []) rather than misleading ones.
"""

import my_config as cfg
from rag.retrieval import RetrievedChunk, retrieve


def procedure_reader(
    query: str,
    context: dict | None,
    top_k: int = 2,
) -> list[RetrievedChunk]:
    """
    Retrieve a small number of chunks as procedure/topic hints
    for the query synthesizer.

    Returns [] if the best chunk score is below MIN_RETRIEVAL_SCORE,
    indicating no clear procedure match — synthesizer should then ask
    for clarification (Issue #2).
    """
    chunks = retrieve(
        query=query,
        context=context,
        top_k=top_k,
    )

    # Filter out chunks that fall below the relevance threshold.
    filtered = [
        chunk for chunk in chunks
        if chunk.retrieval_score >= cfg.MIN_RETRIEVAL_SCORE
    ]

    if filtered:
        print(
            f"[procedure_reader] {len(filtered)}/{len(chunks)} hints "
            f"above threshold ({cfg.MIN_RETRIEVAL_SCORE})."
        )
    else:
        print(
            f"[procedure_reader] All {len(chunks)} hints below "
            f"threshold ({cfg.MIN_RETRIEVAL_SCORE}). Returning []."
        )

    return filtered