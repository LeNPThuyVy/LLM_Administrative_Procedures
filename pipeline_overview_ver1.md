# Pipeline hiện tại (ver1) — Giải thích & Đánh giá

> Review dựa trên source code trong `LLM_Administrative_Procedures/` bản đã nộp (ver1).
> Mục đích: giúp cả nhóm nắm luồng chạy trước khi refactor cho ver2.

---

## 1. Sơ đồ luồng chạy

```
app.py :: respond()
   └─ rag/pipeline.py :: answer_query(query, context)
        1. retrieve()                    → rag/retrieval.py
        2. rerank()                      → rag/rerank.py           (placeholder)
        3. build_evidence_candidates()   → rag/evidence_builder.py
        4. build_prompt()                → rag/prompt_builder.py
        5. generate_answer()             → rag/generator.py
        6. verify_answer()               → rag/verification.py
        7. map_verification_results()    → rag/mapper.py
   └─ trả AnswerResponse(answer, claims)
   └─ app.py cập nhật Gradio Chatbot + Evidence Panel + Clarification Box
```

Kiến trúc tổng thể bám đúng `AI_CORE_CONTRACT.md` (Context Object → RetrievedChunk →
EvidenceCandidate → VerifiedEvidence). Vấn đề nằm ở cách implement bên trong từng bước,
không phải ở kiến trúc tổng.

---

## 2. Chi tiết từng bước

### Bước 1 — Retrieval (`rag/retrieval.py`)
- Query được embed bằng `intfloat/multilingual-e5-small`, prefix `"query: "` (đúng convention của E5).
- Tìm kiếm trên ChromaDB đã persist sẵn (`data/chroma_db`), lấy `top_k = 3` (config trong `my_config.py`).
- **Vấn đề:** `load_embedding_model()` và `load_vector_store()` được gọi lại **mỗi lần** `retrieve()` chạy — không cache. Đây là nguyên nhân chính gây chậm (xem `bugs.md`).

### Bước 2 — Rerank (`rag/rerank.py`)
- Chỉ là **placeholder**: sort lại `RetrievedChunk` theo `retrieval_score` giảm dần — thực chất Chroma đã trả về theo đúng thứ tự này rồi, nên bước này gần như no-op.
- Đúng như kế hoạch ban đầu ("giữ `rerank()` làm placeholder để không block tiến độ"), nhưng cần ghi nhận là nợ kỹ thuật cho ver2 (cross-encoder rerank).

### Bước 3 — Evidence Builder (`rag/evidence_builder.py`)
- Bọc mỗi `RetrievedChunk` thành `EvidenceCandidate` (id dạng `EC_001`, `EC_002`...), giữ nguyên `retrieval_score` làm `rerank_score` tạm thời (vì `RetrievedChunk` chưa có field riêng).

### Bước 4 — Prompt Builder (`rag/prompt_builder.py`)
- Ghép: câu hỏi + ngữ cảnh hội thoại (`recent_messages`) + toàn bộ evidence + **15 quy tắc bắt buộc** (chỉ dùng evidence, không suy luận, format trích dẫn `[EC_00x]`, câu trả lời mặc định khi thiếu thông tin, v.v.)
- **Vấn đề:** Rule #10 minh họa định dạng trích dẫn bằng cách lấy thẳng `evidence_candidates[0].candidate_id` (ID thật) thay vì một placeholder tĩnh — có thể khiến model học nhầm là luôn ưu tiên trích `EC_001`.

### Bước 5 — Generation (`rag/generator.py`)
- Model: **`Qwen/Qwen2.5-0.5B-Instruct`**, chạy local qua `transformers` (không qua API OpenAI/Gemini như plan ban đầu cho demo).
- Có cache đúng cách (`_tokenizer`, `_model` là biến global, chỉ load 1 lần) — đây là điểm làm tốt, ngược lại với `retrieval.py`.
- `DEVICE = "cuda" if available else "cpu"` — trên HF Spaces free tier thường sẽ chạy CPU.
- `MAX_NEW_TOKENS = 512`, `TEMPERATURE = 0.0` (greedy decoding, `do_sample=False`).

### Bước 6 — Verification (`rag/verification.py`)
- Tách câu trả lời thành từng "claim" theo dấu câu, tính độ trùng từ (word-overlap, có loại stopword tiếng Việt) giữa claim và evidence.
- Ngưỡng: `>= 0.35` → `supported`, `>= 0.15` → `partial`, còn lại → rơi vào nhánh fallback.
- **Vấn đề nghiêm trọng:** nhánh fallback (overlap `< 0.15`) vẫn gán `status = "supported"` nếu có evidence, kèm citation vào `evidence_candidates[0]` — dù không liên quan gì. Xem chi tiết ở `bugs.md`.

### Bước 7 — Mapper (`rag/mapper.py`)
- Map `VerificationResult` → `VerifiedClaim` (kèm `Citation`) để trả về UI. Logic đơn giản, không phát hiện vấn đề.

### UI (`app.py`, `ui/`)
- Gradio `Blocks` với `Chatbot`, `Clarification Box`, `Evidence Panel`.
- `needs_clarification` được detect bằng cách check chuỗi cố định `"Thông tin trong tài liệu được cung cấp chưa đủ"` có nằm trong answer — hoạt động được nhưng khá "fragile" (phụ thuộc 100% vào việc model tuân thủ đúng câu chữ ở Rule #7).

---

## 3. Data & Index (`scripts/built_index.py`, `data/procedures.json`)
- 18 thủ tục hành chính, độ dài content trung bình ~759 ký tự (min 233, max 1825).
- Chunking: 1400 ký tự/chunk, overlap 200 — vì content khá ngắn, phần lớn thủ tục chỉ tạo ra **1 chunk duy nhất** (chunking chưa thực sự phát huy tác dụng ở quy mô dữ liệu này).
- Embedding khi build index dùng prefix `"passage: "` — khớp đúng với `"query: "` lúc retrieve (E5 convention đúng chuẩn).

---

## 4. Điểm lệch so với kế hoạch ban đầu
- Kế hoạch demo là dùng **LLM qua API** (OpenAI/Gemini) — nhưng ver1 lại dùng model local nhỏ (0.5B) chạy CPU, khiến vừa chậm vừa yếu về khả năng follow-instruction.
- Yêu cầu "lượng tử hóa" chưa được áp dụng: `requirements.txt` không có `bitsandbytes`/`accelerate`, model load ở `float32` trên CPU.

Chi tiết từng bug cụ thể (mức độ, cách fix đề xuất) → xem file `bugs.md` đi kèm.
