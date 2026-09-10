"""
This file:
- Read procedures.json
- Chunk content
    + Chunk size: 1200-1500 characters
    + Overlap: 200 characters
- Embedding: Multilingual-e5-small
- Save to  chroma


Chroma document ={
    "document_id": "PROC_001",
    "title": ...,
    "category": ...,
    "document_type": ...,
    "chunk_id": "PROC_001_CHUNK_001",
    "processing_time": "...",
    "fee": "..."
}
"""

import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer
import my_config as cfg

#Load procedure
def load_procedures()-> list[dict]:
    """
    Load administrative procedures from procedures.json
    Return list of procedure records
    """
    with open(cfg.PROCEDURES_PATH, "r", encoding="utf-8") as file:
        procedures = json.load(file)

    if not isinstance(procedures, list):
        raise ValueError("procedures.json must contain a JSON list.")

    return procedures


#Chunk text
def chunk_text(text, chunk_size=cfg.CHUNK_SIZE, overlap=cfg.CHUNK_OVERLAP) ->list[str]:
    """
    Split text into overlapping character-based chunks
    Args:
        text: Source text
        chunk_size: Maximum number of characters per chunk
        overlap: Number of overlapping characters
    Returns list of text chunks
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size.")

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap

    return chunks


#Prepare chunks
def prepare_chunks(procedures):
    """
    Convert procedures into ChromaDB documents.

    Each chunk contains:
        - chunk_id
        - document_id
        - content
        - metadata

    Returns:
        list[dict]
    """
    chunks = []

    for procedure in procedures:
        document_id = procedure.get("document_id")
        content = procedure.get("content")

        if not document_id:
            raise ValueError("Procedure is missing document_id")

        if not content or not content.strip():
            raise ValueError(
                f"Procedure {document_id} has empty content."
            )

        text_chunks = chunk_text(content)

        for index, chunk in enumerate(text_chunks, start=1):
            chunk_id = f"{document_id}_CHUNK_{index:03d}"

            metadata = {
                "title": procedure.get("title", ""),
                "category": procedure.get("category", ""),
                "document_type": procedure.get("document_type", ""),
                "processing_time": procedure.get("processing_time", ""),
                "fee": procedure.get("fee", ""),
                "source_url": procedure.get("source_url") or "",
            }

            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "content": chunk,
                    "metadata": metadata,
                }
            )

    return chunks

#Build ChromaDB index
def build_index(chunks):
    """
    Create embeddings and store chunks in ChromaDB.
    """
    print("Loading embedding model")
    model = SentenceTransformer(cfg.EMBEDDING_MODEL)
    texts = [
        f"passage: {chunk['content']}"
        for chunk in chunks
    ]

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True
    )

    print("Creating ChromaDB client")

    cfg.CHROMA_PATH.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(
        path=str(cfg.CHROMA_PATH)
    )

    collection = client.get_or_create_collection(
        name=cfg.COLLECTION_NAME,
        metadata={
            "hnsw:space": "cosine"
        },
    )

    #Prevent duplicate chunks when rebuilding
    if chunks:
        chunk_ids = [chunk["chunk_id"] for chunk in chunks]

        collection.upsert(
            ids=chunk_ids,
            documents=[chunk["content"] for chunk in chunks],
            embeddings=embeddings.tolist()
            metadatas=[
                {
                    **chunk["metadata"],
                    "document_id": chunk["document_id"],
                    "chunk_id": chunk["chunk_id"],
                }
                for chunk in chunks
            ],
        )

    return collection


# 
#Main

def main():
    print("=" * 60)
    print("Building Legal AI RAG Index")
    print("=" * 60)

    #Load source data
    procedures = load_procedures()

    print(f"Procedures loaded: {len(procedures)}")

    #Prepare chunks
    chunks = prepare_chunks(procedures)

    print(f"Chunks prepared: {len(chunks)}")

    # Validation
    document_ids = {
        procedure.get("document_id")
        for procedure in procedures
    }

    chunk_document_ids = {
        chunk["document_id"]
        for chunk in chunks
    }

    chunk_ids = [chunk["chunk_id"] for chunk in chunks]

    # Check document_id preservation
    missing_document_ids = document_ids - chunk_document_ids

    if missing_document_ids:
        raise ValueError(
            f"Some document_ids were lost during chunking: "
            f"{missing_document_ids}"
        )

    # Check chunk_id uniqueness
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("Duplicate chunk_id detected.")

    # Check content
    empty_chunks = [
        chunk["chunk_id"]
        for chunk in chunks
        if not chunk["content"].strip()
    ]

    if empty_chunks:
        raise ValueError(
            f"Empty content detected in chunks: {empty_chunks}"
        )

    print("Validation passed.")

    #Build ChromaDB index
    collection = build_index(chunks)

    # Final statistics
    total_documents = collection.count()

    print()
    print("=" * 60)
    print("Index built successfully!")
    print("=" * 60)
    print(f"Number of procedures : {len(procedures)}")
    print(f"Number of chunks     : {len(chunks)}")
    print(f"ChromaDB documents   : {total_documents}")
    print(f"Persist directory    : {cfg.CHROMA_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
