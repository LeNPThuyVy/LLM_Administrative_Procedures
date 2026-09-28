"""
build_index.py — Xây dựng ChromaDB vector index cho procedures.

GĐ2 mục 6: Gộp build_index.py và built_index.py thành một file duy nhất.
- Tự động loại bỏ các cặp trùng lặp, giữ bản đầy đủ hơn.
- Tạo per-field chunks: _docs, _fee, _time, _method, _general
- Dùng cosine distance (chuẩn cosine space cho similarity search).

Chạy:
    python scripts/build_index.py
"""

import json
import sys
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

# --- Paths ---
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT_DIR / "data" / "procedures.json"
DB_PATH = ROOT_DIR / "data" / "chroma_db"
REMOVED_LOG_PATH = ROOT_DIR / "docs" / "removed_duplicates.md"

# Dùng config embedding model nếu có, fallback về default
try:
    import my_config as cfg
    MODEL_NAME = cfg.EMBEDDING_MODEL
    COLLECTION_NAME = cfg.COLLECTION_NAME
except ImportError:
    MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    COLLECTION_NAME = "procedures"


# =========================================================
# GĐ2 mục 6: Danh sách các cặp trùng
# Format: (giữ_lại, loại_bỏ)
# Xác định từ check_duplicates.py — giữ bản có nội dung đầy đủ hơn.
# =========================================================
DUPLICATE_PAIRS: list[tuple[str, str]] = [
    ("PROC_020", "PROC_008"),  # Trợ cấp hưu trí xã hội
    ("PROC_016", "PROC_010"),  # Hỗ trợ hoả táng
    ("PROC_011", "PROC_015"),  # Trợ cấp thờ cúng liệt sĩ
    ("PROC_019", "PROC_014"),  # Hưởng trợ cấp người có công
    ("PROC_023", "PROC_009"),  # Xác định mức độ khuyết tật
    ("PROC_032", "PROC_028"),  # Vay vốn việc làm
    ("PROC_027", "PROC_025"),  # Cấp giấy phép xây dựng
]

REMOVED_IDS: set[str] = {removed for _, removed in DUPLICATE_PAIRS}


# =========================================================
# PER-FIELD CHUNKING
# =========================================================

def _build_field_chunks(item: dict) -> list[dict]:
    """
    Tạo per-field chunks cho một thủ tục.

    Chunks được tạo:
        PROC_XXX_docs    → title + required_documents
        PROC_XXX_fee     → title + fee
        PROC_XXX_time    → title + processing_time
        PROC_XXX_method  → title + submission_method
        PROC_XXX_general → full content (catch-all)
    """
    doc_id = item["document_id"]
    title = item.get("title", "")

    base_meta = {
        "document_id": doc_id,
        "title": title,
        "document_type": item.get("document_type", ""),
        "category": item.get("category", ""),
        "source_url": item.get("source_url") or "",
    }

    chunks = []

    # 1. Required documents
    docs_text = (item.get("required_documents") or "").strip()
    if docs_text:
        chunks.append({
            "chunk_id": f"{doc_id}_docs",
            "text": f"Tên thủ tục: {title}\nThành phần hồ sơ:\n{docs_text}",
            "metadata": {**base_meta, "chunk_id": f"{doc_id}_docs", "field": "required_documents"},
        })

    # 2. Fee
    fee_text = (item.get("fee") or "").strip()
    if fee_text:
        chunks.append({
            "chunk_id": f"{doc_id}_fee",
            "text": f"Tên thủ tục: {title}\nLệ phí: {fee_text}",
            "metadata": {**base_meta, "chunk_id": f"{doc_id}_fee", "field": "fee"},
        })

    # 3. Processing time
    time_text = (item.get("processing_time") or "").strip()
    if time_text:
        chunks.append({
            "chunk_id": f"{doc_id}_time",
            "text": f"Tên thủ tục: {title}\nThời gian giải quyết: {time_text}",
            "metadata": {**base_meta, "chunk_id": f"{doc_id}_time", "field": "processing_time"},
        })

    # 4. Submission method / location
    method_text = (item.get("submission_method") or "").strip()
    location_text = (item.get("submission_location") or "").strip()
    method_combined = "\n".join(filter(None, [method_text, location_text]))
    if method_combined:
        chunks.append({
            "chunk_id": f"{doc_id}_method",
            "text": f"Tên thủ tục: {title}\nHình thức và nơi nộp hồ sơ:\n{method_combined}",
            "metadata": {**base_meta, "chunk_id": f"{doc_id}_method", "field": "submission_method"},
        })

    # 5. General (full content)
    full_content = (item.get("content") or "").strip()
    if full_content:
        chunks.append({
            "chunk_id": f"{doc_id}_general",
            "text": full_content,
            "metadata": {**base_meta, "chunk_id": f"{doc_id}_general", "field": "general"},
        })
    elif chunks:
        # Fallback: ghép tất cả text lại làm general nếu không có content
        combined = f"Tên thủ tục: {title}\n" + "\n".join(c["text"] for c in chunks)
        chunks.append({
            "chunk_id": f"{doc_id}_general",
            "text": combined,
            "metadata": {**base_meta, "chunk_id": f"{doc_id}_general", "field": "general"},
        })

    return chunks


# =========================================================
# DUPLICATE LOG
# =========================================================

def _write_removed_log(removed: list[dict]) -> None:
    """Ghi danh sách procedure đã loại bỏ vào docs/."""
    REMOVED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Danh sách thủ tục bị loại bỏ do trùng lặp (GĐ2)\n\n",
        "Bản được giữ lại là bản có nội dung đầy đủ hơn.\n\n",
        "| Loại bỏ | Giữ lại | Tiêu đề |\n",
        "|---------|---------|--------|\n",
    ]
    for r in removed:
        lines.append(f"| {r['removed']} | {r['kept']} | {r['title']} |\n")
    REMOVED_LOG_PATH.write_text("".join(lines), encoding="utf-8")
    print(f"   → Ghi log tại: {REMOVED_LOG_PATH}")


# =========================================================
# MAIN
# =========================================================

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("BUILD INDEX — GĐ2 (field chunks + dedup)")
    print("=" * 60)

    # 1. Load data
    print(f"\n1. Đọc {DATA_PATH}...")
    procedures = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    print(f"   Tổng: {len(procedures)} thủ tục")

    # 2. Loại bỏ bản trùng
    removed_log = []
    doc_map = {p["document_id"]: p for p in procedures}
    filtered = []
    for proc in procedures:
        did = proc["document_id"]
        if did in REMOVED_IDS:
            # Tìm kept partner
            kept = next(k for k, r in DUPLICATE_PAIRS if r == did)
            removed_log.append({
                "removed": did,
                "kept": kept,
                "title": proc.get("title", ""),
            })
            print(f"   ✗ Loại bỏ {did} (trùng với {kept}): {proc.get('title','')[:50]}")
        else:
            filtered.append(proc)

    print(f"   → Còn lại: {len(filtered)} thủ tục sau dedup")

    # 3. Build chunks
    print("\n2. Tạo per-field chunks...")
    all_chunks = []
    for proc in filtered:
        all_chunks.extend(_build_field_chunks(proc))
    print(f"   → {len(all_chunks)} chunks "
          f"(~{len(all_chunks)/len(filtered):.1f} chunk/thủ tục)")

    # 4. Validate
    chunk_ids = [c["chunk_id"] for c in all_chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("Duplicate chunk_id detected!")
    print("   ✓ Validation passed")

    # 5. Embedding
    print(f"\n3. Tải embedding model: {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME)

    texts = [c["text"] for c in all_chunks]
    print("4. Tạo embeddings...")
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
        batch_size=32,
    ).tolist()

    # 6. ChromaDB
    print("\n5. Lưu vào ChromaDB...")
    DB_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(DB_PATH))

    try:
        client.delete_collection(name=COLLECTION_NAME)
        print("   → Đã xóa collection cũ")
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    collection.add(
        ids=chunk_ids,
        documents=texts,
        metadatas=[c["metadata"] for c in all_chunks],
        embeddings=embeddings,
    )

    # 7. Write duplicate log
    if removed_log:
        _write_removed_log(removed_log)

    # 8. Summary
    print("\n" + "=" * 60)
    print("HOÀN THÀNH")
    print("=" * 60)
    print(f"Thủ tục được lập chỉ mục : {len(filtered)}")
    print(f"Thủ tục đã loại (trùng)  : {len(removed_log)}")
    print(f"Tổng chunks              : {collection.count()}")
    print(f"Database                 : {DB_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()