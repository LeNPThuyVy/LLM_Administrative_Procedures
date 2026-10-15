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
    raw_results_out: list[RetrievedChunk] | None = None,
    domain: str | None = None,
) -> list[RetrievedChunk]:
    """
    Retrieve a small number of chunks as procedure/topic hints
    for the query synthesizer.

    Returns [] if the best chunk score is below MIN_RETRIEVAL_SCORE,
    indicating no clear procedure match — synthesizer should then ask
    for clarification (Issue #2).
    """
    fetch_k = max(top_k, 15) if raw_results_out is not None else top_k
    chunks = retrieve(
        query=query,
        context=context,
        top_k=fetch_k,
        domain=domain,
    )

    if raw_results_out is not None:
        raw_results_out.extend(chunks)

    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)
    min_score = runtime.min_retrieval_score if (runtime and hasattr(runtime, "min_retrieval_score")) else cfg.MIN_RETRIEVAL_SCORE

    # Filter out chunks that fall below the relevance threshold.
    filtered = [
        chunk for chunk in chunks[:top_k]
        if chunk.retrieval_score >= min_score
    ]

    if filtered:
        print(
            f"[procedure_reader] {len(filtered)}/{len(chunks)} hints "
            f"above threshold ({min_score})."
        )
    else:
        print(
            f"[procedure_reader] All {len(chunks)} hints below "
            f"threshold ({min_score}). Returning []."
        )

    return filtered