def build_evidence_candidates(
    reranked_chunks,
    max_evidence=3
):
    return reranked_chunks[:max_evidence]