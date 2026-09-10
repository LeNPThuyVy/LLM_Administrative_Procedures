import os

import chromadb
from sentence_transformers import SentenceTransformer

from context.schemas import RetrievedChunk


ROOT_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

DB_PATH = os.path.join(
    ROOT_DIR,
    "data",
    "chroma_db"
)

MODEL_NAME = (
    "sentence-transformers/"
    "paraphrase-multilingual-MiniLM-L12-v2"
)


_model = None
_collection = None


def get_model():
    global _model

    if _model is None:
        _model = SentenceTransformer(
            MODEL_NAME
        )

    return _model


def get_collection():
    global _collection

    if _collection is None:

        client = chromadb.PersistentClient(
            path=DB_PATH
        )

        _collection = client.get_collection(
            name="procedures"
        )

    return _collection


def build_search_query(query, context):
    result = query

    structured_context = context.get(
        "structured_context",
        {}
    )

    location = structured_context.get(
        "location"
    )

    if location:
        result += f"\nĐịa điểm: {location}"

    return result


def retrieve(query, context, top_k=3):

    search_query = build_search_query(
        query,
        context
    )

    model = get_model()

    collection = get_collection()

    query_embedding = model.encode(
        [search_query],
        normalize_embeddings=True
    ).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k
    )

    chunks = []

    if not results["ids"]:
        return chunks

    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    for (
        chunk_id,
        content,
        metadata,
        distance
    ) in zip(
        ids,
        documents,
        metadatas,
        distances
    ):

        retrieval_score = max(
            0.0,
            1.0 - float(distance)
        )

        chunk = RetrievedChunk(
            chunk_id=chunk_id,
            document_id=metadata["document_id"],
            content=content,
            retrieval_score=retrieval_score,
            metadata=metadata
        )

        chunks.append(chunk)

    return chunks