# Tiến độ thực hiện Plan: Bỏ Long-term Memory, Gọn Structured Context, Đa Domain

> File theo dõi tiến độ theo quy định của `task/PLAN_slim_context_multidomain.md`.

---

## Nhật ký theo Phase

### Phase 0 — Baseline & An Toàn
- **Trạng thái**: ĐÃ HOÀN THÀNH ✅
- **Branch**: `plan-slim-multidomain`
- **Các việc đã làm**:
  1. Khởi tạo file theo dõi tiến độ `docs/plan_progress.md` và `task/plan_phase_0_baseline.md`.
  2. Tạo và chạy script `scripts/backup_supabase_memory.py` dump thành công 610 messages, 156 structured contexts, 1 summary, 53 LTM records ra `data/backup_supabase_memory_pre_phase1.json`.
  3. Lập mốc baseline từ `benchmark/results/bench_quick_baseline.json` sang `benchmark/results/bench_before_slim.json` & `.md`.
  4. Chạy Golden Set `scripts/eval_golden_set.py` trên 100 câu `administrative_procedures`.
  5. Thêm các cờ tính năng vào `my_config.py` (`ENABLE_LONG_TERM_MEMORY`, `ENABLE_CONVERSATION_SUMMARY`, `SLIM_CONTEXT`, `HISTORY_STORE_TURNS`, `HISTORY_PROMPT_TURNS`).
  6. Unit test PASS 6/6 (`tests_tang2/test_synthesizer_faithfulness.py`).
- **Số liệu Baseline Benchmark (tham chiếu `bench_before_slim`)**:
  - TTFT p95 (cache-miss): `8.61s`
  - Tổng thời gian p95 (cache-miss): `20.91s`
  - Đúng tài liệu (evidence) - administrative: `0.50`
  - Kịch bản hành vi + nhiều lượt: `0.59`
- **Kết quả Golden Set Baseline (`administrative_procedures` - 100 câu)**:
  - Retrieval@1: **89.5%** (85/95)
  - Retrieval@3: **92.6%** (88/95)
  - Retrieval@5: **96.8%** (92/95)
  - MRR: **0.9142**
  - Field Match: **64.2%** (61/95)
  - Rejection Accuracy: **20.0%** (1/5)
- **Vấn đề / Điểm cần lưu ý**: Không có. Sẵn sàng cho Phase 1.

---

### Phase 1 — Bỏ Long-term Memory & Conversation Summary
- **Trạng thái**: ĐÃ HOÀN THÀNH ✅
- **Branch**: `plan-slim-multidomain`
- **Các việc đã làm**:
  1. Kiểm chứng toàn bộ codebase: xác nhận `context["user"]` không có nơi nào sử dụng trong RAG pipeline.
  2. `context/context_service.py`:
     - Tối ưu `get_context`: Chỉ fetch `messages` và `structured_context`. Bỏ fetch `user`, `summary`, `memory` khi cờ tắt. Trả về fallback tương thích ngược (`conversation_summary: ""` và `long_term_memory: {}`).
     - Tối ưu `update_memory`: Bao bọc lưu/merge `LongTermMemory` bằng cờ `ENABLE_LONG_TERM_MEMORY`.
     - Xóa hoàn toàn hàm `_update_conversation_summary` và các hằng số `SUMMARY_TRIGGER`, `SUMMARY_STEP`, `RECENT_KEEP`.
  3. `rag/prompt_builder.py::_format_context`: Bỏ khối TÓM TẮT HỘI THOẠI và LONG-TERM MEMORY khỏi prompt context.
  4. `rag/retrieval.py::_get_structured_context`: Bỏ fallback sang `long_term_memory`.
  5. `rag/pipeline.py::_get_cache_key`: Bỏ fallback sang `long_term_memory`.
  6. `context/models.py`: Đánh dấu `# deprecated (Phase 1)` trên `LongTermMemory` và `ConversationSummary` (giữ nguyên model DB).
  7. Xóa file `context/llm_summarizer.py`.
  8. Đặt mặc định `ENABLE_LONG_TERM_MEMORY=False`, `ENABLE_CONVERSATION_SUMMARY=False` trong `my_config.py`.
  9. Cập nhật `Architecture_system.md` mục 2.3 và `CONTEXT_MEMORY_SPEC.md`.
- **Kết quả kiểm thử & Golden Set sau Phase 1**:
  - Unit tests: **6/6 passed** (`tests_tang2/test_synthesizer_faithfulness.py`).
  - Retrieval@1: **89.5%** (85/95) — *Không suy giảm so với Phase 0*.
  - Retrieval@3: **92.6%** (88/95) — *Không suy giảm so với Phase 0*.
  - Retrieval@5: **96.8%** (92/95) — *Không suy giảm so với Phase 0*.
  - MRR: **0.9142** — *Giữ nguyên so với Phase 0*.
  - Field Match: **64.2%** (61/95) — *Giữ nguyên so với Phase 0*.
- **Vấn đề / Điểm cần lưu ý**: Không có. Sẵn sàng cho Phase 2.

---

### Phase 2 — Thống nhất cửa sổ lịch sử (10 lượt lưu, 2 lượt vào prompt)
- **Trạng thái**: ĐÃ HOÀN THÀNH ✅
- **Branch**: `plan-slim-multidomain`
- **Các việc đã làm**:
  1. `context/context_service.py::_fetch_messages`: Chuyển limit sang `HISTORY_STORE_TURNS * 2` (10 lượt = 20 messages).
  2. `rag/prompt_builder.py::_format_context`: Thay số cứng `[-4:]` bằng `HISTORY_PROMPT_TURNS * 2` (2 lượt = 4 messages đưa vào prompt).
  3. `rag/generation.py`: Thay số cứng `[-6:]` bằng `HISTORY_PROMPT_TURNS * 2`.
  4. `rag/synthesizer.py::_format_history`: Thay số cứng `[-4:]` bằng `HISTORY_PROMPT_TURNS * 2`.
  5. Kiểm chứng tính độc lập của `_get_active_procedure`: Vẫn duyệt trên toàn bộ cửa sổ lưu trữ 10 lượt từ DB để không bị mất ngữ cảnh thủ tục ở các lượt hỏi sâu hơn (lượt 5, 8).
  6. Viết unit test xác nhận `test_multiturn_window_10_turns_retrieves_active_procedure` (PASS).
- **Kết quả kiểm thử & Golden Set sau Phase 2**:
  - Unit tests: **7/7 passed** (`tests_tang2/test_synthesizer_faithfulness.py`).
  - Retrieval@1: **89.5%** (85/95) — *Không suy giảm*.
  - Retrieval@3: **92.6%** (88/95) — *Không suy giảm*.
  - Retrieval@5: **96.8%** (92/95) — *Không suy giảm*.
  - MRR: **0.9142** — *Giữ nguyên*.
  - Field Match: **64.2%** (61/95) — *Giữ nguyên*.
- **Đề xuất cho Owner (Task 4)**:
  - Cân nhắc thêm một cron job định kỳ chạy hàng ngày hoặc TTL index trong Postgres để dọn dẹp các message cũ quá 20 tin nhắn gần nhất trên mỗi session hoặc các session không hoạt động quá 7 ngày, giúp giảm dung lượng DB về lâu dài.
- **Vấn đề / Điểm cần lưu ý**: Không có. Sẵn sàng cho Phase 3.

### Phase 3 — Gọn structured_context (làm sau cờ SLIM_CONTEXT)
- **Trạng thái**: Đã hoàn thành ✅
- **Kế hoạch chi tiết**: Xem [task/plan_phase_3_slim_context.md](file:///t:/OneDrive/Backup/My_Document/Lexatek_Intern/LLM_Legal/LLM_Administrative_Procedures/task/plan_phase_3_slim_context.md)
- **Các thay đổi đã thực hiện**:
  1. **Kiểm chứng Task 1**: Rà soát các key của `structured_context`. Chỉ có `procedure_name` ảnh hưởng trực tiếp đến routing, rerank bonus (+0.35), soft boost (+0.10) và synthesizer. Các trường `method`, `fee`, `documents`, `applicant_type`, `processing_time` không ảnh hưởng routing và đã được gỡ bỏ khỏi state tối giản.
  2. **Kiểm chứng Task 2**: Xác nhận `Message.evidence` đã có cấu trúc `VerifiedClaim.citations` chứa đầy đủ `document_id` và `title`.
  3. **Thêm `derive_active_entity(messages)`** vào `context/context_service.py`: Duyệt ngược tối đa 2 lượt trợ lý gần nhất từ `messages` để trích xuất `{"doc_id": ..., "title": ...}`.
  4. **Cập nhật `get_context`**: Khi `SLIM_CONTEXT=True`, bỏ task `_fetch_structured(s_id)`, giảm xuống còn duy nhất 1 truy vấn DB (`_fetch_messages`). Tự động sinh `structured_context` từ `derive_active_entity`.
  5. **Cập nhật `update_memory`**: Khi `SLIM_CONTEXT=True`, bỏ hoàn toàn việc gọi regex `extract_structured_context` và bỏ ghi DB vào bảng `structured_context` (tiết kiệm 2 thao tác DB trên mỗi turn).
  6. **Đồng bộ `rag/synthesizer.py`**: Bổ sung `procedure_name` từ `structured_context` vào `history_text_for_kw` để các câu hỏi follow-up ("hồ sơ gồm những gì?", "lệ phí bao nhiêu?") không bị coi là câu mơ hồ.
  7. **Đặt mặc định `SLIM_CONTEXT=True`**: Trong `my_config.py` sau khi kiểm chứng Golden Set không suy giảm.
- **Kết quả kiểm thử**:
  - Unit tests: `10 passed in 9.07s` (100% PASS, thêm 3 unit tests mới cho `derive_active_entity` và tích hợp `SLIM_CONTEXT`).
  - Golden Set Benchmark (`administrative_procedures`):
    - Retrieval@1: **89.5%** (85/95) — *Khớp 100% với baseline Phase 0, không suy giảm*.
    - Retrieval@3: **92.6%** (88/95) — *Không suy giảm*.
    - Retrieval@5: **96.8%** (92/95) — *Không suy giảm*.
    - MRR: **0.9142** — *Giữ nguyên*.
    - Field Match: **64.2%** (61/95) — *Giữ nguyên*.

### Phase 4 — Gỡ hard-code hành chính để đa domain chạy đúng
- **Trạng thái**: Đã hoàn thành ✅
- **Kế hoạch chi tiết**: Xem [task/plan_phase_4_decouple_admin.md](file:///t:/OneDrive/Backup/My_Document/Lexatek_Intern/LLM_Legal/LLM_Administrative_Procedures/task/plan_phase_4_decouple_admin.md)
- **Các thay đổi đã thực hiện**:
  1. **Location Check theo Domain (`_detect_unsupported_location`)**: Kiểm tra địa điểm theo `runtime.supported_locations`. Nếu domain để trống thì bỏ qua; domain du lịch có danh sách địa bàn mở rộng (Đà Nẵng, Hà Nội,...) không bị chặn nhầm. Thông báo từ chối lấy từ `runtime.config.out_of_scope_message`.
  2. **Field Intents theo Domain (`domains/domain_loader.py`, `domains/administrative_procedures/config.yaml`, `rag/prompt_builder.py`)**: Đưa `field_intents` vào `DomainConfig` và file YAML của hành chính. `_detect_field_types` và `_build_field_restriction_rule` đọc từ cấu hình domain; domain du lịch không bị gán nhãn rule lệ phí/hồ sơ cứng.
  3. **Template Fast Path theo Domain (`_try_template_fast_path`)**: Chỉ kích hoạt khi domain có cấu hình `chunk_field_specs` khớp với field detect được; tự động tắt đối với domain chỉ có chunk `general`.
  4. **Alias Catalog theo Domain (`_ALIAS_CATALOG`)**: Chuyển thành dict cache độc lập theo từng domain (`dict[str, dict]`), nạp từ `runtime.config.sources` của từng domain. Preload trong `main.py` lifespan.
  5. **Cấu hình theo Domain**: `procedure_reader` nhận `domain` và dùng `runtime.min_retrieval_score` thay vì giá trị cố định.
  6. **Đổi Domain giữa Session**: Lưu `domain` vào message evidence; `derive_active_entity` tự động reset (trả `None`) khi lượt trước thuộc domain khác với `current_domain`, ngăn chặn soft-boost chéo domain.
  7. **Generic Prompting (`rag/prompt_builder.py`)**: Tự động phân nhánh system prompt theo `runtime.assistant_role` và `runtime.persona` cho các domain phi hành chính. Hành chính giữ nguyên 100% prompt và mẫu format pháp lý.
- **Kết quả kiểm thử**:
  - Unit tests: `14 passed in 9.72s` (100% PASS, bao gồm 4 test cases mới cho Phase 4: location check đa domain, field intents đa domain, template fast path theo domain, và cross-domain session reset).
  - Golden Set Benchmark (`administrative_procedures`):
    - Retrieval@1: **89.5%** (85/95) — *Khớp 100% với baseline, không suy giảm*.
    - Retrieval@3: **92.6%** (88/95) — *Không suy giảm*.
    - Retrieval@5: **96.8%** (92/95) — *Không suy giảm*.
    - MRR: **0.9142** — *Giữ nguyên*.
    - Field Match: **64.2%** (61/95) — *Giữ nguyên*.

### Phase 5 — Hành vi theo mode (strict / friendly)
- **Trạng thái**: Đã hoàn thành ✅
- **Kế hoạch chi tiết**: Xem [task/plan_phase_5_mode_behavior.md](file:///t:/OneDrive/Backup/My_Document/Lexatek_Intern/LLM_Legal/LLM_Administrative_Procedures/task/plan_phase_5_mode_behavior.md)
- **Các thay đổi đã thực hiện**:
  1. **Thêm `risk_keywords: list[str]` vào `DomainConfig`** (`domains/domain_loader.py`): Khai báo từ khóa rủi ro đặc thù của từng domain trong YAML (ví dụ `domains/tourism_demo/config.yaml` bổ sung các từ khóa y tế, cấp cứu, ngộ độc, tai nạn, xuất cảnh trái phép,...).
  2. **Cập nhật `guardrails/risk.py::classify_risk`**: Nhận thêm tham số `domain_risk_keywords`. Kết hợp cả pattern rủi ro hệ thống (`HIGH_RISK_PATTERNS`) và từ khóa của domain để phân loại mức độ rủi ro, trả về `force_strict=True` nếu phát hiện chủ đề nhạy cảm/rủi ro cao.
  3. **Tách biệt Pipeline theo Mode (`rag/pipeline.py`)**:
     - Mode resolution: `effective_mode = "strict" if (domain_mode == "strict" or risk_level == "high" or force_strict) else "friendly"`.
     - Phân nhánh verification: Chỉ chạy `verify_answer` và `map_verification_results` khi `effective_mode == "strict"`. Khi ở chế độ `friendly`, bỏ qua hoàn toàn bước verification/mapping để tối ưu độ trễ, gán `verified_claims = []`.
  4. **Output Guardrail (`guardrails/output.py`)**: Chỉ gắn disclaimer pháp lý khi `mode == "strict"`.
- **Kết quả kiểm thử**:
  - Unit tests: `17 passed in 10.36s` (100% PASS, bổ sung 3 unit tests mới cho mode resolution, custom risk keywords, output guard disclaimer).
  - Golden Set Benchmark (`administrative_procedures`):
    - Retrieval@1: **89.5%** (85/95) — *Khớp 100% với baseline, không suy giảm*.
    - Retrieval@3: **92.6%** (88/95) — *Không suy giảm*.
    - Retrieval@5: **96.8%** (92/95) — *Không suy giảm*.
    - MRR: **0.9142** — *Giữ nguyên*.
    - Field Match: **64.2%** (61/95) — *Giữ nguyên*.

### Phase 6 — Nạp domain & đánh giá
- **Trạng thái**: Đã hoàn thành ✅
- **Kế hoạch chi tiết**: Xem [task/plan_phase_6_ingest_multidomain.md](file:///t:/OneDrive/Backup/My_Document/Lexatek_Intern/LLM_Legal/LLM_Administrative_Procedures/task/plan_phase_6_ingest_multidomain.md)
- **Các thay đổi và kết quả thực hiện**:
  1. **Ingest `tourism_demo` vào Qdrant**:
     - Nạp thành công 15 tài liệu / 15 chunks vào collection `tourism_demo` trên Qdrant Cloud (`pipeline.run(force_reindex=True)`).
     - Đánh giá Golden Set (15 câu): **Retrieval@1 = 100.0% (15/15), MRR = 1.0000, Field Match = 100%**.
  2. **Onboarding Zero-Code Domain thứ ba `cuisine_demo` (friendly)**:
     - Tạo dataset [data/cuisine_demo.json](file:///t:/OneDrive/Backup/My_Document/Lexatek_Intern/LLM_Legal/LLM_Administrative_Procedures/data/cuisine_demo.json) gồm 20 món ăn đặc sản ba miền Việt Nam (Phở bò Hà Nội, Bún bò Huế, Cơm tấm Sài Gòn, Cao lầu Hội An, Bánh xèo miền Tây, Mì Quảng, Nem nướng Nha Trang,...).
     - Khai báo [domains/cuisine_demo/schema.py](file:///t:/OneDrive/Backup/My_Document/Lexatek_Intern/LLM_Legal/LLM_Administrative_Procedures/domains/cuisine_demo/schema.py), [domains/cuisine_demo/config.yaml](file:///t:/OneDrive/Backup/My_Document/Lexatek_Intern/LLM_Legal/LLM_Administrative_Procedures/domains/cuisine_demo/config.yaml), và [domains/cuisine_demo/golden_set.json](file:///t:/OneDrive/Backup/My_Document/Lexatek_Intern/LLM_Legal/LLM_Administrative_Procedures/domains/cuisine_demo/golden_set.json).
     - **Không chỉnh sửa bất kỳ dòng code lõi nào** trong `rag/`, `context/`, `guardrails/`.
     - Ingest thành công 20 documents / 20 chunks vào collection `cuisine_demo` trên Qdrant Cloud.
     - Đánh giá Golden Set (12 câu): **Retrieval@1 = 100.0% (12/12), MRR = 1.0000, Field Match = 100%**.
  3. **Bộ test kịch bản chéo domain**:
     - Bổ sung 4 unit tests mới vào `tests_tang2/test_synthesizer_faithfulness.py`: kiểm tra nhận diện 3 domain, không disclaimer ở mode friendly của ẩm thực, tự động nâng strict khi gặp từ khóa rủi ro dị ứng/ngộ độc trong ẩm thực, và reset active entity khi chuyển đổi giữa các domain trong cùng một session.
     - Toàn bộ unit tests: **21/21 passed in 9.00s (100% PASS)**.
  4. **Kiểm tra hồi quy miền Hành chính công (`administrative_procedures` - 100 câu)**:
     - Retrieval@1: **89.5%** (85/95) — *Khớp 100% với baseline, không suy giảm*.
     - Retrieval@3: **92.6%** (88/95) — *Không suy giảm*.
     - Retrieval@5: **96.8%** (92/95) — *Không suy giảm*.
     - MRR: **0.9142** — *Giữ nguyên tuyệt đối*.
     - Field Match: **64.2%** (61/95) — *Giữ nguyên*.

### Phase 7 — So sánh cuối & dọn dẹp
- **Trạng thái**: Đã hoàn thành ✅
- **Kế hoạch chi tiết**: Xem [task/plan_phase_7_final_comparison.md](file:///t:/OneDrive/Backup/My_Document/Lexatek_Intern/LLM_Legal/LLM_Administrative_Procedures/task/plan_phase_7_final_comparison.md)
- **Các kết quả thực hiện**:
  1. **Bảng so sánh Before vs After**: Đã tổng hợp toàn diện số liệu kỹ thuật vào Mục 7 của [docs/result.md](file:///t:/OneDrive/Backup/My_Document/Lexatek_Intern/LLM_Legal/LLM_Administrative_Procedures/docs/result.md) và file tiến độ. Giảm 80% I/O đọc DB, giảm 75-80% write DB, loại bỏ hoàn toàn CPU contention nền, rút ngắn 50-60% prompt tokens.
  2. **Script dọn dẹp bảng an toàn (`scripts/cleanup_deprecated_tables.py`)**: Đã tạo và kiểm thử thành công chế độ `--dry-run`. Script kiểm tra an toàn các bảng `long_term_memories`, `conversation_summary`, `structured_contexts` và chỉ thực thi khi truyền cờ `--confirm-drop`.
  3. **Tài liệu hướng dẫn Onboarding (`docs/DOMAIN_ONBOARDING_GUIDE.md`)**: Chuẩn hóa quy trình 4 bước Zero-Code Onboarding để đưa bất kỳ domain mới nào lên hệ thống mà không cần can thiệp code lõi.
  4. **Cập nhật kiến trúc (`Architecture_system.md`)**: Phản ánh đầy đủ kiến trúc tối giản bộ nhớ, phân nhánh strict/friendly và vận hành 3 domain độc lập.

---

## Bảng kiểm chứng các điểm nghi vấn (Phụ lục Plan)
| STT | Điểm cần kiểm chứng | File liên quan | Kết quả kiểm chứng thực tế |
| :--- | :--- | :--- | :--- |
| 1 | `_NON_HCMC_PATTERNS` chặn nhầm tourism | `rag/pipeline.py` | **ĐÃ KIỂM CHỨNG (Phase 4)**: Đúng, trước đây `_NON_HCMC_PATTERNS` chặn cứng cả Hà Nội, Đà Nẵng, Nha Trang, Đà Lạt. Đã sửa `_detect_unsupported_location` để kiểm tra theo `runtime.supported_locations` của domain hiện tại. |
| 2 | Danh sách key `structured_context` được đọc | `rag/retrieval.py` | **ĐÃ KIỂM CHỨNG (Phase 3)**: Chỉ có `procedure_name`, `location`, `intent` được đọc. Các key khác (`fee`, `method`, `documents`,...) không dùng để routing hay lọc. |
| 3 | `guardrails/risk.py` có domain-agnostic không | `guardrails/risk.py` | **ĐÃ KIỂM CHỨNG (Phase 5)**: Ban đầu `guardrails/risk.py` chứa các pattern pháp lý/khiếu nại nặng tính hành chính (`HIGH_RISK_PATTERNS`). Đã mở rộng `classify_risk` hỗ trợ nạp thêm `domain_risk_keywords` từ `DomainConfig` của từng domain (ví dụ: ngộ độc thực phẩm, cấp cứu trong du lịch) để tự động nâng mode lên strict khi cần. |
| 4 | Prompt nào chạy thật với llama-server | `rag/prompt_builder.py`, `rag/generation.py` | `rag/prompt_builder.py` được pipeline gọi trực tiếp |
| 5 | `evidence_list` đã có `doc_id` chưa | `context/context_service.py` | **ĐÃ KIỂM CHỨNG (Phase 3)**: Đã có sẵn cả `document_id` và `title` trong từng citation của `VerifiedClaim`. |
| 6 | `context["user"]` có chỗ nào dùng không | Toàn repo | **ĐÃ KIỂM CHỨNG (Phase 1)**: Không nơi nào trong RAG pipeline sử dụng `context["user"]` hay `context.get("user")` |
