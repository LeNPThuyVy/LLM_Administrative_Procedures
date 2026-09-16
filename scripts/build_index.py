import json
import os

import chromadb
from sentence_transformers import SentenceTransformer


ROOT_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

DATA_PATH = os.path.join(
    ROOT_DIR,
    "data",
    "procedures.json"
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


def main():
    print("1. Dang doc procedures.json...")

    with open(
        DATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:
        procedures = json.load(f)

    print(
        f"2. Tim thay {len(procedures)} thu tuc."
    )

    print("3. Dang tai embedding model...")

    model = SentenceTransformer(
        MODEL_NAME
    )

    print("4. Dang mo ChromaDB...")

    client = chromadb.PersistentClient(
        path=DB_PATH
    )

    try:
        client.delete_collection(
            name="procedures"
        )
    except Exception:
        pass

    collection = client.create_collection(
        name="procedures"
    )

    ids = []
    documents = []
    metadatas = []

    for item in procedures:
        chunk_id = (
            item["document_id"]
            + "_chunk_1"
        )

        ids.append(
            chunk_id
        )

        documents.append(
            item["content"]
        )

        metadatas.append({
            "chunk_id": chunk_id,
            "document_id": item["document_id"],
            "title": item["title"],
            "agency": item.get("agency", ""),
            "page": item.get(
                "page_number",
                item.get("page", 1)
            )
        })

    print("5. Dang tao embedding...")

    embeddings = model.encode(
        documents,
        normalize_embeddings=True
    ).tolist()

    print("6. Dang luu vao ChromaDB...")

    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings
    )

    print("\nHOAN THANH")
    print("Database:", DB_PATH)


if __name__ == "__main__":
    main()