# ChromaDB Migration Notes

- Ngày thực hiện: 2026-10-05
- Thực hiện bởi: Role C (Runtime & Eval)

## Kiểm tra phụ thuộc ChromaDB (`grep -rn "chroma" --include=*.py .`)

### Các file đã được kiểm tra:
1. `rag/retrieval.py`: **Đã cập nhật** sang `QdrantClient` + `BGEM3FlagModel` (BGE-M3 1024-dim), loại bỏ hoàn toàn `chromadb` import trong runtime search.
2. `my_config.py`: **Đã cập nhật** thêm cấu hình `QDRANT_URL`, `QDRANT_API_KEY`, `DEFAULT_DOMAIN`, `DEFAULT_COLLECTION`, `EMBEDDING_MODEL = "BAAI/bge-m3"`. Đánh dấu `CHROMA_PATH` là deprecated.
3. `requirements.txt`: **Đã thêm** `qdrant-client` và `FlagEmbedding`. Giữ lại `chromadb` và `sentence-transformers` để phục vụ các script cũ cho tới nghiệm thu cuối.
4. `scripts/tmp_chroma_to_qdrant.py`: Script tạm phục vụ đổ dữ liệu từ ChromaDB cũ sang collection Qdrant `admin_dev`.
5. `scripts/build_index.py` & `scripts/built_index.py`: Giữ nguyên theo đúng thỏa thuận hợp đồng chung (không xóa trong ngày hôm nay).
6. `rag/procedure_reader.py`, `rag/evidence_builder.py`, `rag/rerank.py`, `rag/synthesizer.py`, `rag/pipeline.py`: Không gọi trực tiếp `chromadb` (chỉ tiêu thụ interface `retrieve` và dataclass `RetrievedChunk`). **Không cần sửa**.

## Kết luận:
- Runtime search đã độc lập 100% với ChromaDB.
- Toàn bộ contract của `RetrievedChunk` và signature `retrieve()`, `retrieve_two_step()` được bảo toàn.
