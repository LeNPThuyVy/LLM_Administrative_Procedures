# Báo cáo Triển khai Plan C (Tầng 1 Domain Onboarding - Runtime & Eval)

- **Ngày nghiệm thu**: 2026-10-05
- **Nhánh**: `feat/layer1-c`
- **Người thực hiện**: Role C (Runtime & Eval)

---

## 1. Tóm tắt công việc đã hoàn thành

1. **Migration Vector Search Engine**:
   - Chuyển đổi thành công `rag/retrieval.py` từ **ChromaDB + MiniLM (384-dim)** sang **Qdrant Cloud + BGE-M3 (1024-dim)**.
   - Cập nhật API sang `query_points` với `with_payload=True`.
   - Điều chỉnh công thức xếp hạng sử dụng trực tiếp Qdrant cosine similarity score kết hợp `keyword_bonus` và `context_bonus`.
   - Giữ nguyên 100% interface của `retrieve()` và `retrieve_two_step()`, hỗ trợ thêm tham số `domain`.

2. **Cấu hình & Quản lý Môi trường**:
   - Bổ sung cấu hình Qdrant Cloud (`QDRANT_URL`, `QDRANT_API_KEY`, `DEFAULT_DOMAIN`, `DEFAULT_COLLECTION`) vào `my_config.py`.
   - Cập nhật `requirements.txt` với `qdrant-client` và `FlagEmbedding`.

3. **Công cụ Chuyển đổi & Đánh giá**:
   - Tạo script `scripts/tmp_chroma_to_qdrant.py` phục vụ đổ dữ liệu thử nghiệm từ ChromaDB cũ lên Qdrant collection `admin_dev`.
   - Xây dựng `scripts/eval_golden_set.py` phục vụ tính toán các chỉ số **Retrieval@1, @3, @5 và MRR**.

4. **Tài liệu & Kiểm soát phụ thuộc**:
   - Ghi lại số liệu baseline ban đầu vào `docs/baseline_before_qdrant.md`.
   - Điền đầy đủ danh sách các metadata keys thực tế vào Mục 9 của `test/00_hop_dong_chung.md`.
   - Tổng hợp ghi chú quét phụ thuộc ChromaDB vào `docs/migration_notes.md`.

---

## 2. Kết quả Đánh giá (Evaluation Metrics)

### 2.1 Single-Turn & Golden Set Evaluation (Qdrant + BGE-M3)
- **Doc Hit@1 (`eval_fast.py`)**: **29/30 = 96.7%** (Baseline MiniLM: 95.0%)
- **Retrieval@1 (`eval_golden_set.py`)**: **27/30 = 90.0%**
- **Retrieval@3 (`eval_golden_set.py`)**: **28/30 = 93.3%**
- **Retrieval@5 (`eval_golden_set.py`)**: **28/30 = 93.3%** *(Mục tiêu DoD: ≥ 80% - Đạt!)*
- **MRR (Mean Reciprocal Rank)**: **0.9167**

---

## 3. Tiêu chí hoàn thành (Definition of Done)

- [x] `retrieve()` và `retrieve_two_step()` chạy trên Qdrant, bảo toàn interface.
- [x] Dữ liệu chuyển đổi mượt mà, hỗ trợ cả Qdrant Cloud lẫn local storage fallback.
- [x] Đã chuẩn bị đầy đủ bộ công cụ đánh giá `eval_golden_set.py` và bài thử nghiệm `eval_fast.py`.
- [x] Retrieval@5 trên golden set đạt **93.3%** (vượt chỉ tiêu 80%).
- [x] ChromaDB và `build_index.py` cũ giữ nguyên không bị phá vỡ.
