"""
Build (or rebuild) the ChromaDB vector index for procedures.

Issue #4 fix: instead of indexing one chunk per procedure (all fields merged),
split each procedure into per-field chunks:

    PROC_XXX_docs    → title + required_documents
    PROC_XXX_fee     → title + fee
    PROC_XXX_time    → title + processing_time
    PROC_XXX_method  → title + submission_method
    PROC_XXX_general → full original content (overview / catch-all)

Advantages:
- Retrieval targets only the specific field the user asks about.
- Reduces false-positive evidence from unrelated fields in the same chunk.
- Works together with prompt_builder.py field-restriction rules (Issue #5).
"""

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


def _build_field_chunks(item: dict) -> list[dict]:
    """
    Build per-field chunks for a single procedure item.

    Returns a list of dicts with keys:
        chunk_id, document_id, title, field, text, metadata
    """
    doc_id = item["document_id"]
    title = item.get("title", "")

    # Reusable base metadata shared across all chunks of this procedure.
    base_meta = {
        "document_id": doc_id,
        "title": title,
        "agency": item.get("agency", ""),
        "page": item.get("page_number", item.get("page", 1)),
    }

    chunks = []

    # 1. Required documents chunk
    docs_text = item.get("required_documents", "").strip()
    if docs_text:
        chunks.append({
            "chunk_id": f"{doc_id}_docs",
            "field": "required_documents",
            "text": f"Tên thủ tục: {title}\nThành phần hồ sơ:\n{docs_text}",
            "metadata": {**base_meta, "chunk_id": f"{doc_id}_docs", "field": "required_documents"},
        })

    # 2. Fee chunk
    fee_text = item.get("fee", "").strip()
    if fee_text:
        chunks.append({
            "chunk_id": f"{doc_id}_fee",
            "field": "fee",
            "text": f"Tên thủ tục: {title}\nLệ phí: {fee_text}",
            "metadata": {**base_meta, "chunk_id": f"{doc_id}_fee", "field": "fee"},
        })

    # 3. Processing time chunk
    time_text = item.get("processing_time", "").strip()
    if time_text:
        chunks.append({
            "chunk_id": f"{doc_id}_time",
            "field": "processing_time",
            "text": f"Tên thủ tục: {title}\nThời gian giải quyết: {time_text}",
            "metadata": {**base_meta, "chunk_id": f"{doc_id}_time", "field": "processing_time"},
        })

    # 4. Submission method chunk
    method_text = item.get("submission_method", "").strip()
    if method_text:
        chunks.append({
            "chunk_id": f"{doc_id}_method",
            "field": "submission_method",
            "text": f"Tên thủ tục: {title}\nHình thức nộp: {method_text}",
            "metadata": {**base_meta, "chunk_id": f"{doc_id}_method", "field": "submission_method"},
        })

    # 5. General (full content) chunk — always present as a fallback
    full_content = item.get("content", "").strip()
    if full_content:
        chunks.append({
            "chunk_id": f"{doc_id}_general",
            "field": "general",
            "text": full_content,
            "metadata": {**base_meta, "chunk_id": f"{doc_id}_general", "field": "general"},
        })

    return chunks


def main():
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("1. Đang đọc procedures.json...")

    with open(
        DATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:
        procedures = json.load(f)

    print(
        f"2. Tìm thấy {len(procedures)} thủ tục."
    )

    # Build per-field chunks for all procedures.
    all_chunks = []
    for item in procedures:
        all_chunks.extend(_build_field_chunks(item))

    print(
        f"   → Tổng số chunks sau khi split: {len(all_chunks)} "
        f"(trung bình {len(all_chunks) / len(procedures):.1f} chunk/thủ tục)"
    )

    print("3. Đang tải embedding model...")

    model = SentenceTransformer(MODEL_NAME)

    print("4. Đang mở ChromaDB...")

    client = chromadb.PersistentClient(
        path=DB_PATH
    )

    try:
        client.delete_collection(
            name="procedures"
        )
        print("   → Đã xóa collection cũ.")
    except Exception:
        pass

    collection = client.create_collection(
        name="procedures"
    )

    ids = [c["chunk_id"] for c in all_chunks]
    documents = [c["text"] for c in all_chunks]
    metadatas = [c["metadata"] for c in all_chunks]

    print("5. Đang tạo embeddings...")

    embeddings = model.encode(
        documents,
        normalize_embeddings=True,
        show_progress_bar=True,
    ).tolist()

    print("6. Đang lưu vào ChromaDB...")

    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings
    )

    print(f"\nHOÀN THÀNH — {len(all_chunks)} chunks được lập chỉ mục.")
    print("Database:", DB_PATH)


if __name__ == "__main__":
    main()