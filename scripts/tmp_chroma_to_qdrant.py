"""
scripts/tmp_chroma_to_qdrant.py — Temporary migration script from ChromaDB to Qdrant.

Reads existing Chroma collection and upserts chunks into Qdrant collection `admin_dev`
using BGE-M3 dense embeddings (1024-dim, cosine distance).
"""

import os
import sys
import uuid
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import my_config as cfg
import chromadb
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

def get_qdrant_client() -> QdrantClient:
    """Return QdrantClient instance (Cloud if configured, else local storage)."""
    if cfg.QDRANT_URL:
        print(f"Connecting to Qdrant Cloud at: {cfg.QDRANT_URL}")
        return QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY)
    
    local_path = ROOT_DIR / "data" / "qdrant_db"
    local_path.mkdir(parents=True, exist_ok=True)
    print(f"QDRANT_URL not set in .env. Using local Qdrant storage at: {local_path}")
    return QdrantClient(path=str(local_path))

def load_embedder():
    """Load BGE-M3 embedder using SentenceTransformer for fast multi-threaded CPU inference."""
    from sentence_transformers import SentenceTransformer
    print(f"Loading BGE-M3 model using SentenceTransformer ('BAAI/bge-m3')...")
    model = SentenceTransformer("BAAI/bge-m3")
    return lambda texts: model.encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=16).tolist()

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("MIGRATE CHROMADB -> QDRANT (admin_dev)")
    print("=" * 60)

    # 1. Connect to ChromaDB
    chroma_path = cfg.CHROMA_PATH
    if not chroma_path.exists():
        raise FileNotFoundError(f"Chroma DB path not found: {chroma_path}")

    print(f"\n1. Reading ChromaDB from {chroma_path}...")
    chroma_client = chromadb.PersistentClient(path=str(chroma_path))
    try:
        chroma_col = chroma_client.get_collection(name="procedures")
    except Exception as e:
        print(f"Collection 'procedures' not found, falling back to default collection. Err: {e}")
        collections = chroma_client.list_collections()
        if not collections:
            raise RuntimeError("No collections found in ChromaDB.")
        chroma_col = collections[0]

    data = chroma_col.get(include=["documents", "metadatas"])
    ids = data.get("ids", [])
    documents = data.get("documents", [])
    metadatas = data.get("metadatas", [])

    print(f"   Found {len(ids)} items in ChromaDB.")
    if not ids:
        print("   No data to migrate!")
        return

    # 2. Setup Qdrant Client & Collection
    qdrant = get_qdrant_client()
    collection_name = getattr(cfg, "DEFAULT_COLLECTION", "admin_dev")

    # Recreate collection
    print(f"\n2. Setting up Qdrant collection '{collection_name}' (dim=1024, distance=Cosine)...")
    try:
        qdrant.recreate_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=cfg.EMBEDDING_DIM, distance=Distance.COSINE),
        )
    except Exception:
        # Fallback if recreate_collection deprecated in client version
        if qdrant.collection_exists(collection_name):
            qdrant.delete_collection(collection_name)
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=cfg.EMBEDDING_DIM, distance=Distance.COSINE),
        )

    # 3. Embed & Upsert in Batches
    print("\n3. Embedding documents and upserting into Qdrant...")
    embed_fn = load_embedder()

    batch_size = 50
    total = len(ids)

    for i in range(0, total, batch_size):
        batch_ids = ids[i : i + batch_size]
        batch_docs = documents[i : i + batch_size]
        batch_metas = metadatas[i : i + batch_size]

        embeddings = embed_fn(batch_docs)

        points = []
        for raw_id, doc, meta in zip(batch_ids, batch_docs, batch_metas):
            meta = meta or {}
            chunk_id = meta.get("chunk_id") or raw_id
            doc_id = meta.get("document_id") or raw_id.split("_")[0]

            payload = {
                **meta,
                "text": doc,
                "chunk_id": chunk_id,
                "document_id": doc_id,
                "domain": meta.get("domain", cfg.DEFAULT_DOMAIN),
            }

            # Generate deterministic UUID v5 from chunk_id
            point_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id))

            points.append(
                PointStruct(
                    id=point_uuid,
                    vector=embeddings[len(points)],
                    payload=payload,
                )
            )

        qdrant.upsert(collection_name=collection_name, points=points)
        print(f"   Upserted {min(i + batch_size, total)}/{total} points...")

    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print(f"Collection '{collection_name}' count: {qdrant.count(collection_name).count}")
    print("=" * 60)

if __name__ == "__main__":
    main()
