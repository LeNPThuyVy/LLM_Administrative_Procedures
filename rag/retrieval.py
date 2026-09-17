"""
Query processing, embedding and vector search.

Return RetrievedChunk objects.
"""

import re
from dataclasses import dataclass

import chromadb
from sentence_transformers import SentenceTransformer

import my_config as cfg


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    content: str
    retrieval_score: float
    metadata: dict


# Module-level singletons — loaded once, reused across all queries
_embedding_model: SentenceTransformer | None = None
_chroma_collection = None


# Model / Vector Store
def load_embedding_model() -> SentenceTransformer:
    """
    Load embedding model only once.
    """
    global _embedding_model

    if _embedding_model is None:
        _embedding_model = SentenceTransformer(
            cfg.EMBEDDING_MODEL
        )

    return _embedding_model


def load_vector_store():
    """
    Load existing persistent ChromaDB.
    """
    client = chromadb.PersistentClient(
        path=str(cfg.CHROMA_PATH)
    )

    collection = client.get_collection(
        name=cfg.COLLECTION_NAME
    )

    return collection


def _get_embedding_model() -> SentenceTransformer:
    """
    Return the cached embedding model, loading it on first call.

    Subsequent calls reuse the same instance.
    """
    global _embedding_model

    if _embedding_model is None:
        _embedding_model = load_embedding_model()

    return _embedding_model


def _get_chroma_collection():
    """
    Return the cached Chroma collection, loading it on first call.

    Subsequent calls reuse the same instance.
    """
    global _chroma_collection

    if _chroma_collection is None:
        _chroma_collection = load_vector_store()

    return _chroma_collection


# Query Processing
def build_search_query(
    query: str,
    context: dict | None = None
) -> str:
    """
    Build search query from user query and structured context.
    """
    query = query.strip()

    if not context:
        return query

    structured_context = context.get(
        "structured_context",
        {}
    )

    if not structured_context:
        return query

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
        return query

    return (
        query
        + " "
        + " ".join(context_parts)
    )


def _normalize_words(text: str) -> set[str]:
    """
    Convert text into useful lowercase words.
    """
    if not text:
        return set()

    words = re.findall(
        r"\w+",
        text.lower(),
        flags=re.UNICODE
    )

    stopwords = {
        "thủ",
        "tục",
        "cần",
        "những",
        "giấy",
        "tờ",
        "gì",
        "là",
        "có",
        "không",
        "để",
        "và",
        "các",
        "hồ",
        "sơ",
    }

    return {
        word
        for word in words
        if word not in stopwords
    }


def _calculate_keyword_bonus(
    query: str,
    metadata: dict,
    content: str
) -> float:
    """
    Prefer results whose title directly matches
    important words in the user's query.
    """
    query_words = _normalize_words(query)

    title = str(
        metadata.get("title", "")
    )

    title_words = _normalize_words(title)
    content_words = _normalize_words(content)

    if not query_words:
        return 0.0

    title_overlap = len(
        query_words.intersection(title_words)
    )

    content_overlap = len(
        query_words.intersection(content_words)
    )

    # Title match is much more important.
    bonus = (
        title_overlap * 0.30
        + content_overlap * 0.03
    )

    return bonus


def retrieve(
    query: str,
    context: dict | None = None,
    top_k: int = cfg.DEFAULT_TOP_K
) -> list[RetrievedChunk]:
    """
    Retrieve relevant chunks.

    First use vector search, then improve ranking
    using title/query keyword overlap.
    """
    if not query or not query.strip():
        return []

    if top_k <= 0:
        return []

    search_query = build_search_query(
        query=query,
        context=context
    )

    # Load embedding model
    model = _get_embedding_model()

    query_embedding = model.encode(
        search_query,
        normalize_embeddings=True
    ).tolist()

    # Load persistent ChromaDB
    collection = _get_chroma_collection()

    # Retrieve candidate chunks
    collection_count = collection.count()

    candidate_count = min(
        max(top_k * 5, 10),
        collection_count
    )

    if candidate_count <= 0:
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=candidate_count
    )

    documents = results.get(
        "documents",
        [[]]
    )[0]

    metadatas = results.get(
        "metadatas",
        [[]]
    )[0]

    distances = results.get(
        "distances",
        [[]]
    )[0]

    retrieved_chunks = []

    for content, metadata, distance in zip(
        documents,
        metadatas,
        distances
    ):
        metadata = metadata or {}

        chunk_id = str(
            metadata.get(
                "chunk_id",
                ""
            )
        )

        document_id = str(
            metadata.get(
                "document_id",
                ""
            )
        )

        # Vector score: higher is better.
        vector_score = 1.0 / (
            1.0 + float(distance)
        )

        keyword_bonus = _calculate_keyword_bonus(
            query=query,
            metadata=metadata,
            content=content
        )

        final_score = (
            vector_score
            + keyword_bonus
        )

        retrieved_chunks.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                content=content,
                retrieval_score=final_score,
                metadata=metadata
            )
        )

    # Highest score first.
    retrieved_chunks.sort(
        key=lambda item: item.retrieval_score,
        reverse=True
    )

    return retrieved_chunks[:top_k]
