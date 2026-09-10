from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer
import my_config as cfg


#RetrievedChunk
@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    content: str
    retrieval_score: float
    metadata: dict


# Model/Vector Store

def load_embedding_model() -> SentenceTransformer:
    """
    Load the same embedding model used when building ChromaDB.
    """
    return SentenceTransformer(cfg.EMBEDDING_MODEL)


def load_vector_store():
    """
    Load the existing persistent ChromaDB collection.

    This function does NOT rebuild the index.
    """
    client = chromadb.PersistentClient(
        path=str(cfg.CHROMA_DB_PATH)
    )

    collection = client.get_collection(
        name=cfg.COLLECTION_NAME
    )

    return collection


# Query Processing
def build_search_query(
    query: str,
    context: dict | None = None
) -> str:
    """
    Build a simple search query from the original query
    and useful structured context.

    Priority:
    1. structured_context
    2. original query

    The function does not infer new information.
    """

    if not context:
        return query.strip()

    structured_context = context.get(
        "structured_context",
        {}
    )

    if not structured_context:
        return query.strip()

    context_parts = []

    for key, value in structured_context.items():
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        context_parts.append(
            f"{key}: {value}"
        )

    if not context_parts:
        return query.strip()

    context_text = " ".join(context_parts)

    return f"{query.strip()} {context_text}"


# ============================================================
# Retrieval
def retrieve(
    query: str,
    context: dict | None = None,
    top_k: int = DEFAULT_TOP_K
) -> list[RetrievedChunk]:
    """
    Retrieve top-k relevant chunks from ChromaDB.
    """

    if not query or not query.strip():
        return []

    if top_k <= 0:
        return []

    # --------------------------------------------------------
    # 1. Build search query
    # --------------------------------------------------------

    search_query = build_search_query(
        query=query,
        context=context
    )

    # --------------------------------------------------------
    # 2. Load embedding model
    # --------------------------------------------------------

    model = load_embedding_model()

    # --------------------------------------------------------
    # 3. Embed query
    # --------------------------------------------------------

    # E5 models expect "query: " prefix for queries.
    query_embedding = model.encode(
        f"query: {search_query}",
        normalize_embeddings=True
    ).tolist()

    # --------------------------------------------------------
    # 4. Load persistent ChromaDB
    # --------------------------------------------------------

    collection = load_vector_store()

    # --------------------------------------------------------
    # 5. Vector search
    # --------------------------------------------------------

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )

    # --------------------------------------------------------
    # 6. Convert Chroma result -> RetrievedChunk
    # --------------------------------------------------------

    retrieved_chunks = []

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for content, metadata, distance in zip(
        documents,
        metadatas,
        distances
    ):
        metadata = metadata or {}

        chunk_id = str(
            metadata.get("chunk_id", "")
        )

        document_id = str(
            metadata.get("document_id", "")
        )

        # Chroma distance: lower = more similar.
        # Retrieval score: higher = more relevant.
        retrieval_score = 1.0 / (1.0 + float(distance))

        retrieved_chunks.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                content=content,
                retrieval_score=retrieval_score,
                metadata=metadata
            )
        )

    return retrieved_chunks