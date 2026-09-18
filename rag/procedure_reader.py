from rag.retrieval import RetrievedChunk, retrieve


def procedure_reader(
    query: str,
    context: dict | None,
    top_k: int = 2,
) -> list[RetrievedChunk]:
    """
    Retrieve a small number of chunks as procedure/topic hints
    for the query synthesizer.
    """
    return retrieve(
        query=query,
        context=context,
        top_k=top_k,
    )