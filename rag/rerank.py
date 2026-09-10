from context.schemas import EvidenceCandidate


def rerank(chunks):
    results = []

    for chunk in chunks:
        item = EvidenceCandidate(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            content=chunk.content,
            retrieval_score=chunk.retrieval_score,
            rerank_score=chunk.retrieval_score,
            metadata=chunk.metadata
        )

        results.append(item)

    results.sort(
        key=lambda x: x.rerank_score,
        reverse=True
    )

    return results