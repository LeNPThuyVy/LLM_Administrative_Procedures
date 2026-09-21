# Bugs / UX Issues Log

> Dùng chung cho cả nhóm. Test trên HF Space đã deploy, không test local.
> Format mỗi entry: ngày giờ, người phát hiện, mô tả, mức độ, trạng thái.

## Template

```
### [YYYY-MM-DD HH:mm] Tiêu đề ngắn gọn
- Người phát hiện:
- Câu hỏi test (nếu có, xem demo_questions.md #):
- Mô tả lỗi / kết quả thực tế:
- Kết quả kỳ vọng:
- Mức độ: Blocker / Nên fix / Nice-to-have
- Trạng thái: Mở /Đã fix
- Ghi chú thêm:
```

---

## Log

### [2026-09-13 00:00] Retrieval load lại embedding model + Chroma client mỗi query
- Người phát hiện: Thuy
- Câu hỏi test (nếu có, xem demo_questions.md #): áp dụng cho mọi câu hỏi
- Mô tả lỗi / kết quả thực tế: Trong `rag/retrieval.py`, hàm `retrieve()` gọi `load_embedding_model()` và `load_vector_store()` ở mỗi lần gọi, không cache. Mỗi câu hỏi của user đều load lại `SentenceTransformer` từ đĩa và tạo mới `chromadb.PersistentClient`, làm tăng độ trễ đáng kể — đây là nguyên nhân chính khiến model "chạy chậm".
- Kết quả kỳ vọng: Model embedding và Chroma client chỉ được load 1 lần (singleton, tương tự cách `rag/generator.py` đang cache `_tokenizer`/`_model`), các lần gọi sau tái sử dụng.
- Mức độ: Blocker
- Trạng thái: Đã fix (2026-09-14)
- Ghi chú thêm: Fix nhanh nhất: thêm biến module-level `_model = None`, `_collection = None` giống pattern trong `generator.py`.

### [2026-09-13 00:00] Verification fallback gán "supported" sai cho claim không liên quan
- Người phát hiện: Thuy 
- Câu hỏi test (nếu có, xem demo_questions.md #): bất kỳ câu hỏi nào model trả lời có claim không khớp evidence
- Mô tả lỗi / kết quả thực tế: Trong `rag/verification.py::verify_answer()`, khi độ trùng từ (word-overlap) giữa claim và evidence `< 0.15`, code vẫn gán `status = "supported"` (miễn có evidence_candidates) và tự động gắn citation vào `evidence_candidates[0]` dù nội dung không liên quan. Hệ quả: câu trả lời sai/bịa vẫn hiển thị như đã được xác minh kèm nguồn.
- Kết quả kỳ vọng: Khi overlap thấp, status nên là `"unsupported"` và không tự gán evidence không liên quan.
- Mức độ: Blocker
- Trạng thái: Đã fix (2026-09-14)
- Ghi chú thêm: Đây là nguyên nhân chính khiến layer verification "không có tác dụng" chống hallucination — ảnh hưởng trực tiếp đến độ tin cậy hiển thị trên Evidence Panel.

### [2026-09-13 00:00] Model sinh câu trả lời (0.5B) quá nhỏ so với độ phức tạp của prompt
- Người phát hiện: Thuy
- Câu hỏi test (nếu có, xem demo_questions.md #): các câu hỏi cần trả lời tuân thủ nhiều quy tắc cùng lúc
- Mô tả lỗi / kết quả thực tế: `my_config.py` dùng `Qwen/Qwen2.5-0.5B-Instruct` chạy local qua `transformers`, thay vì gọi API (OpenAI/Gemini) như kế hoạch demo ban đầu. Prompt trong `prompt_builder.py` yêu cầu tuân theo 15 quy tắc cùng lúc (chỉ dùng evidence, format trích dẫn, câu trả lời mặc định...) — model 0.5B thường không đủ khả năng follow-instruction ở mức độ này, dẫn đến output kém.
- Kết quả kỳ vọng: Trả lời đúng trọng tâm, tuân thủ quy tắc trích dẫn, không lặp/lan man.
- Mức độ: Blocker
- Trạng thái:Mở
- Ghi chú thêm: Với giai đoạn demo, nên cân nhắc quay lại dùng LLM qua API để đảm bảo chất lượng, để dành việc chọn/fine-tune model nhỏ cho roadmap sau (đúng như đã chốt: fine-tune/quantize không phải blocker cho demo).

### [2026-09-13 00:00] rerank() chỉ là no-op, chưa cải thiện độ liên quan
- Người phát hiện: Thuy
- Câu hỏi test (nếu có, xem demo_questions.md #): câu hỏi mà top-3 kết quả embedding chưa thực sự là đoạn liên quan nhất
- Mô tả lỗi / kết quả thực tế: `rag/rerank.py` chỉ sort lại theo `retrieval_score` — giá trị này đã đúng thứ tự ngay từ kết quả Chroma trả về, nên bước rerank hiện tại không thay đổi gì.
- Kết quả kỳ vọng: Đã biết trước và chấp nhận được cho demo (placeholder theo đúng kế hoạch), nhưng cần track như nợ kỹ thuật.
- Mức độ: Nice-to-have (cho demo) / cần nâng cấp cho ver2
- Trạng thái:Mở
- Ghi chú thêm: Đề xuất ver2: thêm cross-encoder rerank nếu embedding top-k chưa đủ chính xác.

### [2026-09-13 00:00] Prompt rule #10 hard-code candidate ID thật làm ví dụ định dạng
- Người phát hiện: Thuy
- Câu hỏi test (nếu có, xem demo_questions.md #): —
- Mô tả lỗi / kết quả thực tế: Trong `prompt_builder.py`, ví dụ định dạng trích dẫn ở rule #10 lấy trực tiếp `evidence_candidates[0].candidate_id` (ví dụ `[EC_001]`) thay vì dùng placeholder tĩnh, có thể khiến model học nhầm là luôn nên trích `EC_001` bất kể evidence nào thực sự liên quan.
- Kết quả kỳ vọng: Dùng placeholder cố định kiểu `[EC_XXX]` trong hướng dẫn định dạng, không phụ thuộc vào evidence thực tế của từng query.
- Mức độ: Nên fix
- Trạng thái:Mở
- Ghi chú thêm: Fix đơn giản, không tốn nhiều effort.

### [2026-09-13 00:00] Chưa áp dụng quantization dù đây là yêu cầu ban đầu của dự án
- Người phát hiện: Thuy
- Câu hỏi test (nếu có, xem demo_questions.md #): —
- Mô tả lỗi / kết quả thực tế: `requirements.txt` không có `bitsandbytes`/`accelerate`; `generator.py` load model ở `torch.float32` khi chạy CPU — chưa hề lượng tử hóa dù đây là 1 trong 2 yêu cầu chính của dự án.
- Kết quả kỳ vọng: Ghi nhận rõ đây là roadmap sau demo (đã thống nhất không phải blocker), tránh hiểu nhầm là đã hoàn thành.
- Mức độ: Nice-to-have (cho demo)
- Trạng thái:Mở
- Ghi chú thêm: Theo kế hoạch đã chốt, fine-tune + quantization là roadmap item, không block demo.
