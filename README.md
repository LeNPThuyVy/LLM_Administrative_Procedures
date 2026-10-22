# Hệ thống Trợ lý AI Pháp lý & Thủ tục Hành chính (LLM Administrative Procedures)

Hệ thống **RAG (Retrieval-Augmented Generation)** đa miền (Multi-domain), chuyên biệt cho việc tra cứu, tư vấn **Thủ tục Hành chính công tại TP. Hồ Chí Minh** (chế độ *Strict*) và hỗ trợ mở rộng không cần sửa code lõi (*Zero-Code Domain Onboarding*) sang các miền khác như **Du lịch (`tourism_demo`)** hay **Ẩm thực (`cuisine_demo`)** (chế độ *Friendly*).

Tài liệu này tổng hợp chi tiết:
1. **Luồng hoạt động tổng thể của toàn bộ hệ thống (End-to-End Workflows)**
2. **Cách hệ thống xử lý từng khâu (Stage-by-Stage Processing)**
3. **Công cụ & Công nghệ sử dụng ở từng khâu (Technology Stack)**
4. **Phân tích các điểm yếu & hạn chế hiện tại của hệ thống (System Weaknesses & Bottlenecks)**

---

## 1. Tổng hợp Luồng Hoạt động Toàn Hệ thống (End-to-End Workflows)

Hệ thống được chia thành **3 luồng vận hành chính**:
- **Luồng 1 (Offline / Chuẩn bị dữ liệu)**: Ingestion & Vector Indexing Pipeline.
- **Luồng 2 (Khởi động Server)**: Lifespan Preload & Dual `llama-server` Warmup.
- **Luồng 3 (Online / Thời gian thực)**: Xử lý hội thoại người dùng qua WebSocket (`/ws/chat`) hoặc REST SSE (`/api/chat`) kết hợp quản lý ngữ cảnh PostgreSQL và RAG Core Pipeline.

### 1.1. Sơ đồ Kiến trúc & Luồng Xử lý Tổng thể

```mermaid
flowchart TD
    subgraph Client_Layer["1. Giao diện & Kết nối (Frontend & Transport)"]
        UI["Web UI (HTML5 / Vanilla JS)"]
        Cookie["Bootstrap Session Cookie (user_id 30d, session_id 7d)"]
        UI -->|GET /api/session/bootstrap| Cookie
        UI <-->|WS /ws/chat hoặc POST /api/chat SSE| Gateway["FastAPI Gateway (backend/main.py)"]
    end

    subgraph Concurrency_Context["2. Điều phối & Ngữ cảnh (Queue & Context Layer)"]
        Gateway --> Lock["QueueManager: Session Lock + Global Semaphore (LLAMA_PARALLEL=1)"]
        Lock --> GetCtx["Context Service: get_context()"]
        GetCtx <--> PG[("PostgreSQL Async (sessions, messages)")]
        GetCtx --> ActiveEntity["derive_active_entity(): Trích xuất thực thể từ top-1 Citation gần nhất"]
    end

    subgraph RAG_Core["3. Lõi xử lý RAG (rag/pipeline.py :: answer_query)"]
        ActiveEntity --> Step1["B1. Input Guardrail (Chặn Prompt Injection & Mask PII)"]
        Step1 --> Step2["B2. Answer Cache (_PIPELINE_ANSWER_CACHE theo session_id)"]
        Step2 -->|Cache Miss| Step3["B3. Domain Runtime & Risk Classifier (Tự nâng friendly -> strict nếu rủi ro cao)"]
        Step3 --> Step4["B4. Out-of-Scope Location Check (Kiểm tra địa bàn ngoài TP.HCM)"]
        Step4 --> IntentCheck{"Multi-Intent Enabled & >=2 sub-queries?"}
        
        IntentCheck -->|Có (Chỉ trên SSE)| MultiFlow["Multi-Intent Orchestrator (detector -> resolver -> section template)"]
        IntentCheck -->|Không (Single-Intent)| Step5["B5. History & Procedure Reader (Lấy 2 gợi ý + raw_results_out)"]
        
        Step5 --> Step6["B6. Query Synthesizer (Rule-based Bypass hoặc Qwen2.5-1.5B)"]
        Step6 -->|needs_clarification = True| Clarify["Trả câu hỏi làm rõ (Clarification)"]
        Step6 -->|needs_clarification = False| Step7["B7. Two-Step Retrieval (BGE-M3 + Alias/Keyword/Context Bonus + Negation Filter)"]
        
        Step7 --> Threshold{"Strict Mode & top_score < min_retrieval_score?"}
        Threshold -->|Có (< 0.50)| Fallback["Trả thông báo từ chối (No Evidence)"]
        Threshold -->|Không (>= 0.50)| Step8["B8. Reranker & Evidence Builder (Gắn mã [EC_001], [EC_002]...)"]
        
        Step8 --> Step9["B9. Field Detection & Prompt Builder (Giới hạn trường: docs/fee/time/method)"]
        Step9 --> FastPath{"Đủ điều kiện Template Fast Path?"}
        FastPath -->|Có (1 field cụ thể)| DirectRender["Kết xuất trực tiếp từ Chunk (< 0.1s)"]
        FastPath -->|Không| Step10["B10. LLM Generator (Streaming qua Qwen2.5-3B)"]
        
        DirectRender --> Step11["B11. Fact Verification & Citation Mapper (Kiểm tra từ vựng, số liệu, phủ định)"]
        Step10 --> Step11
        Step11 --> Step12["B12. Output Guardrail (Redaction PII + Đính kèm Disclaimer Pháp lý)"]
    end

    subgraph Serving_Storage["4. Hạ tầng Mô hình & Lưu trữ"]
        Step5 <--> Qdrant[("Qdrant Vector DB (Local / Cloud)")]
        Step7 <--> Qdrant
        Step6 -.->|HTTP :8081| Llama15B["llama-server: Qwen2.5-1.5B-Instruct (Q4_K_M)"]
        Step10 -.->|HTTP :8080| Llama3B["llama-server: Qwen2.5-3B-Instruct (Q4_K_M)"]
        Step12 --> UpdateMem["update_memory() (Async Background Task -> PostgreSQL)"]
    end
```

---

## 2. Hiện tại Hệ thống Xử lý Từng Khâu Như Thế Nào?

### Khâu 1: Thu thập, Chia nhỏ và Đánh chỉ mục Dữ liệu (Data Ingestion & Indexing)
- **Files đảm nhiệm**: `ingestion/pipeline.py`, `ingestion/loaders.py`, `ingestion/chunker.py`, `ingestion/embedder.py`, `ingestion/dedup.py`, `ingestion/vector_store.py`, `ingestion/version.py`.
- **Cách xử lý**:
  1. **Load & Validate**: Đọc dữ liệu nguồn từ `data/procedures.json` (hoặc CSV, DOCX, PDF, JSON của các domain như `data/tourism_demo.json`, `data/cuisine_demo.json`) và kiểm tra tính hợp lệ của schema (`domains/schemas.py`).
  2. **Field-based Chunking (`FieldChunker`)**: Thay vì cắt văn bản thuần túy theo độ dài ký tự, mỗi thủ tục hành chính được tách thành **5 loại chunk chức năng** mang hậu tố định danh riêng:
     - `_general`: Thông tin chung, tên thủ tục, cơ quan thực hiện.
     - `_docs`: Thành phần hồ sơ, số lượng bộ hồ sơ.
     - `_fee`: Lệ phí / chi phí thực hiện.
     - `_time`: Thời hạn giải quyết.
     - `_method`: Cách thức và địa điểm nộp hồ sơ.
  3. **Deduplication & Version Tracking**: Loại bỏ các chunk trùng lặp ngữ nghĩa (`SimilarityDeduplicator`) và lưu dấu vân tay SHA-256 vào `data/.ingestion_versions.json` (`VersionTracker`) để tránh nạp trùng khi chạy lại.
  4. **Embedding & Upsert**: Mã hóa văn bản thành vector dày (dense vector) **1024 chiều** bằng mô hình đa ngôn ngữ `BAAI/bge-m3` (chuẩn hóa L2 `normalize_embeddings=True`) và đẩy vào collection tương ứng trên **Qdrant**.

---

### Khâu 2: Khởi động Hệ thống & Làm nóng Tài nguyên (Server Startup & Warmup)
- **File đảm nhiệm**: `backend/main.py`.
- **Cách xử lý**:
  - Khi `FastAPI` khởi chạy qua `lifespan`, hệ thống không chặn luồng chính mà kích hoạt bất đồng bộ (`asyncio.create_task`):
    1. Khởi tạo bảng PostgreSQL (`init_db()`).
    2. Nạp mô hình `BAAI/bge-m3` vào RAM, kết nối Qdrant, nạp danh mục từ đồng nghĩa (`_ALIAS_CATALOG`) và chạy thử 1 truy vấn mẫu (`encode_query("thủ tục hành chính đăng ký kết hôn")`) để PyTorch cấp phát sẵn bộ nhớ tensor.
    3. Khởi chạy **2 tiến trình `llama-server` độc lập** bằng `subprocess.Popen`:
       - **Port 8080**: Chạy `Qwen2.5-3B-Instruct-Q4_K_M.gguf` (`--ctx-size 4096`, `--threads 4`, `--parallel 1`, `--flash-attn auto`, `--cache-reuse 256`) cho nhiệm vụ sinh câu trả lời chính.
       - **Port 8081**: Chạy `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf` (`--ctx-size 2048`, `--threads 2`, `--parallel 1`) cho nhiệm vụ tổng hợp câu hỏi (Query Synthesizer).
    4. Gửi request mồi (`max_tokens: 1`) tới cả 2 port để nạp trọng số GGUF vào CPU cache, đồng thời cập nhật trạng thái lên endpoint `/api/system/status` cho giao diện theo dõi.

---

### Khâu 3: Quản lý Phiên, Hàng đợi & Ngữ cảnh Hội thoại (Session, Queue & Context Management)
- **Files đảm nhiệm**: `backend/api/socket.py`, `backend/api/sessions.py`, `backend/services/queue_service.py`, `context/context_service.py`.
- **Cách xử lý**:
  1. **Định danh ẩn danh qua Cookie (`bootstrap_session`)**: Tự động cấp `user_id` (lưu 30 ngày) và `session_id` (lưu 7 ngày) qua cookie `HttpOnly` để người dùng có thể tạo phiên mới, chuyển đổi giữa 30 phiên gần nhất hoặc F5 trình duyệt mà không mất lịch sử chat và chip trích dẫn `[EC_xxx]`.
  2. **Kiểm soát đồng thời 2 lớp (`QueueManager`)**:
     - **Lớp 1 (`session_lock`)**: Mỗi `session_id` có một `asyncio.Lock()` riêng, đảm bảo các tin nhắn của cùng một người dùng được xử lý tuần tự.
     - **Lớp 2 (`semaphore`)**: `asyncio.Semaphore(LLAMA_PARALLEL)` (mặc định bằng `1`) giới hạn toàn hệ thống chỉ chạy đồng thời đúng 1 tiến trình suy luận LLM để tránh hiện tượng tranh chấp CPU (CPU thrashing).
  3. **Rút gọn Ngữ cảnh (`SLIM_CONTEXT = True`)**:
     - Khi đọc ngữ cảnh đầu vào (`get_context`), hệ thống chỉ thực hiện **1 truy vấn SQL duy nhất** lấy tối đa 10 lượt hội thoại gần nhất (`20 messages`) từ PostgreSQL.
     - Thay vì dùng LLM hay bộ biểu thức chính quy nặng nề để bóc tách thực thể lưu vào bảng riêng, hàm `derive_active_entity(messages)` đọc trực tiếp trích dẫn `citations[0]["title"]` từ `Message.evidence` của câu trả lời trợ lý gần nhất để xác định **thủ tục đang hội thoại (`active_procedure`)**.
     - Khi lưu kết quả (`update_memory`), hệ thống chạy ngầm (`asyncio.create_task`) sau khi đã trả xong luồng stream cho người dùng, giúp không cộng thêm độ trễ DB vào thời gian phản hồi.

---

### Khâu 4: Kiểm duyệt Đầu vào, Phân loại Rủi ro & Kiểm tra Phạm vi (Guardrails, Risk & Scope)
- **Files đảm nhiệm**: `guardrails/input.py`, `guardrails/risk.py`, `rag/pipeline.py`, `domains/runtime.py`.
- **Cách xử lý**:
  1. **Input Guardrail (`validate_input`)**: Quét các mẫu tấn công Prompt Injection tiếng Anh & tiếng Việt (`ignore previous instructions`, `bỏ qua hướng dẫn`, `system prompt`,...) và ẩn số CCCD 12 số / số điện thoại trong log (`mask_sensitive_for_log`).
  2. **Session-partitioned Answer Cache (`_PIPELINE_ANSWER_CACHE`)**: Tra cứu bộ nhớ đệm tối đa 500 phần tử theo khóa `(session_id, normalized_query, active_procedure, domain)`. Nếu trúng cache, trả kết quả ngay lập tức (~0.00s).
  3. **Risk Classifier & Mode Resolution (`classify_risk`, `resolve_mode`)**:
     - Mỗi domain có chế độ mặc định (`strict` cho hành chính công, `friendly` cho du lịch/ẩm thực).
     - Nếu câu hỏi chứa từ khóa nhạy cảm/rủi ro cao (pháp lý, khiếu nại, xử phạt, ngộ độc, dị ứng, thuốc điều trị...), hệ thống lập tức bật cờ `force_strict = True`, ép chế độ xử lý từ `friendly` sang `strict` (bắt buộc có bằng chứng và cảnh báo miễn trừ trách nhiệm).
  4. **Out-of-Scope Location Gate (`_detect_unsupported_location`)**: Kiểm tra tin nhắn hiện tại với danh sách các tỉnh/thành ngoài phạm vi hỗ trợ (Hà Nội, Đà Nẵng, Bình Dương, Đồng Nai,...). Nếu vi phạm trong domain chỉ hỗ trợ TP.HCM, hệ thống từ chối ngay mà không gọi LLM.

---

### Khâu 5: Tiền xử lý Đa tác tử & Tổng hợp Câu hỏi (Procedure Hint & Query Synthesizer)
- **Files đảm nhiệm**: `rag/history_reader.py`, `rag/procedure_reader.py`, `rag/synthesizer.py`.
- **Cách xử lý**:
  1. **Procedure Reader (`procedure_reader`)**: Truy vấn nhanh Qdrant lấy `top_k = 2` thủ tục gợi ý sát nhất với câu hỏi hiện tại, đồng thời lưu lại danh sách chunk thô vào biến `raw_results_out` để bước Retrieval chính tái sử dụng (tránh phải gọi Qdrant lần 2 nếu câu hỏi không đổi).
  2. **Query Synthesizer (`synthesizer`)** với chế độ tối ưu `SYNTHESIZER_MODE = "rule"`:
     - **Chặn câu chào / câu hỏi mơ hồ**: Nếu người dùng chỉ gõ *"xin chào"*, *"cho tôi hỏi"*, *"tôi muốn làm giấy tờ"* mà không có tên thủ tục cụ thể, hệ thống bật `needs_clarification = True` và yêu cầu người dùng làm rõ ngay lập tức (không gọi LLM).
     - **Turn 1 Rule Bypass**: Nếu câu hỏi lượt đầu đã chứa từ khóa thực thể (`entity_keywords`) hoặc bí danh (`aliases` như *"đẻ con"*, *"mất giấy khai sinh"*, *"mở quán"*), hệ thống bỏ qua model 1.5B, giữ nguyên câu hỏi gốc (tiết kiệm ~4–6 giây).
     - **Follow-up Rule Bypass**: Nếu đang ở lượt hỏi tiếp theo (ví dụ: *"lệ phí bao nhiêu?"*, *"nộp ở đâu?"*) và trong phiên đã có `active_procedure` (ví dụ: *"Thủ tục đăng ký kết hôn"*), hệ thống tự động nối ngữ cảnh theo mẫu: `"{query} (liên quan đến: {active_procedure})"` mà không cần gọi model 1.5B (tiết kiệm ~10–40 giây trên CPU).
     - **Fallback sang LLM 1.5B**: Chỉ khi bật `SYNTHESIZER_MODE = "llm"` hoặc trường hợp tham chiếu phức tạp không bắt được bằng luật, hệ thống mới gọi `Qwen2.5-1.5B` (Port 8081) kèm bước kiểm tra chống bịa số liệu (`_is_faithful`).

---

### Khâu 6: Truy xuất Hai bước & Chấm điểm Lai (Two-Step Retrieval & Hybrid Scoring)
- **File đảm nhiệm**: `rag/retrieval.py`.
- **Cách xử lý**:
  - Hàm `retrieve_two_step()` giải quyết bài toán **"nhầm lẫn mảnh thông tin giữa các thủ tục khác nhau"** (ví dụ: lấy nhầm chunk lệ phí của *khai tử* khi đang hỏi *khai sinh*) thông qua 2 bước:
    - **Bước 6.1 — Định vị Tài liệu Đích (`target_doc_id`)**:
      - Mã hóa câu hỏi bằng `BAAI/bge-m3` (có LRU Cache `_QUERY_EMBEDDING_CACHE` lưu 1000 truy vấn) và lấy các ứng viên từ Qdrant (`top_k * 2`).
      - Tính toán **Điểm thưởng Lai (Hybrid Bonus)** cộng vào điểm Cosine Similarity gốc:
        1. **Alias Bonus (`_calculate_alias_bonus`)**: Cộng điểm lớn (`+0.15` đến `+0.35`) nếu câu hỏi khớp với từ khóa bình dân trong catalog `aliases` (ví dụ: *"mới đẻ con"* -> khớp `Thủ tục đăng ký khai sinh`).
        2. **Negation Penalty (`_is_negated_phrase`)**: Phát hiện ngữ cảnh phủ định (ví dụ: *"đăng ký khai sinh khi **chưa đăng ký kết hôn**"*). Cụm *"đăng ký kết hôn"* đứng sau từ phủ định *"chưa"* sẽ bị phạt điểm để không lấn át thủ tục chính là *"khai sinh"*.
        3. **Keyword Overlap Bonus (`_calculate_keyword_bonus`)**: Cộng tối đa `+0.20` dựa trên tỷ lệ trùng khớp từ khóa với tiêu đề thủ tục (`title`).
        4. **Soft Context Boost (`_calculate_context_bonus`)**: Cộng nhẹ `+0.15` cho các chunk thuộc thủ tục đang active trong phiên (`active_procedure`), vừa giữ mạch hội thoại vừa cho phép người dùng đổi sang thủ tục mới nếu câu hỏi mới có điểm khớp từ khóa/alias cao hơn.
      - Chọn ra `target_doc_id` có tổng điểm cao nhất.
    - **Bước 6.2 — Gom toàn bộ Chunk của Tài liệu Đích**:
      - Dùng bộ lọc metadata `Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=target_doc_id))])` trên Qdrant để lấy đầy đủ các chunk thành phần (`_general`, `_docs`, `_fee`, `_time`, `_method`) của đúng thủ tục đó.
      - Nếu người dùng chỉ hỏi đích danh 1 trường (ví dụ: `fee`), hệ thống ưu tiên đẩy chunk `_fee` và `_general` lên đầu.
  - **Cổng chặn Điểm tối thiểu (`MIN_RETRIEVAL_SCORE = 0.50`)**: Ở chế độ `strict`, nếu chunk cao điểm nhất vẫn `< 0.50`, pipeline dừng ngay và trả thông báo không đủ dữ liệu (`FALLBACK_TEXT`) để triệt tiêu ảo giác (hallucination).

---

### Khâu 7: Sắp xếp lại, Đóng gói Bằng chứng & Xây dựng Prompt (Rerank, Evidence & Prompt Builder)
- **Files đảm nhiệm**: `rag/rerank.py`, `rag/evidence_builder.py`, `rag/prompt_builder.py`.
- **Cách xử lý**:
  1. **Lightweight Lexical & N-gram Reranker (`rerank`)**: Tính điểm thưởng khớp cụm từ liên tiếp (bigram/trigram) giữa câu hỏi và nội dung chunk (`< 2ms`, không tốn thêm RAM) để phân định thứ bậc giữa các chunk có điểm vector gần nhau.
  2. **Evidence Builder (`build_evidence_candidates`)**: Đóng gói từng chunk thành đối tượng `EvidenceCandidate` và cấp mã định danh tuần tự `[EC_001]`, `[EC_002]`, `[EC_003]`...
  3. **Field Restriction & Prompt Builder (`build_prompt`)**:
     - Nhận diện ý định trường thông tin (`_detect_field_types`) theo thứ tự ưu tiên: `method` -> `docs` -> `fee` -> `time`.
     - Sinh quy tắc hướng dẫn mềm (`_build_field_restriction_rule`) để mô hình tập trung vào đúng phần người dùng hỏi.
     - Lắp ghép System Prompt theo cấu hình từng domain (`strict` ép trích dẫn `[EC_xxx]` ở cuối mỗi câu trả lời và cấm suy diễn; `friendly` cho phép văn phong tự nhiên).

---

### Khâu 8: Sinh Câu trả lời (Template Fast Path hoặc LLM 3B Streaming)
- **Files đảm nhiệm**: `rag/pipeline.py`, `rag/generator.py`.
- **Cách xử lý**:
  1. **Nhánh tăng tốc — Template Fast Path (`_try_template_fast_path`)**:
     - Khi câu hỏi chỉ hỏi **đúng 1 trường cụ thể** (`fee`, `time`, `method`, hoặc `docs`) và trong tập bằng chứng đã có sẵn chunk tương ứng (`_fee`, `_time`, `_method`, `_docs`), hệ thống trích xuất trực tiếp nội dung chuẩn từ chunk đó kèm mã `[EC_xxx]` và trả về ngay lập tức (**độ trễ < 0.1 giây**, bỏ qua hoàn toàn bước gọi LLM 3B).
  2. **Nhánh chuẩn — LLM Streaming Generation (`stream_answer_3b`)**:
     - Với câu hỏi tổng quát hoặc đa trường, hệ thống gửi HTTP POST (`stream=True`, `temperature=0.0`, `max_tokens=512`) tới `llama-server` Port 8080 (`Qwen2.5-3B-Instruct`).
     - Các token sinh ra được đẩy qua `asyncio.Queue` trong `backend/services/ai_service.py` để stream thời gian thực về trình duyệt.
  3. **Cơ chế Cứu hộ (`_is_useless_answer` & `_answer_from_evidence`)**:
     - Nếu LLM gặp lỗi kết nối, trả chuỗi rỗng, hoặc chỉ sinh ra mã `[EC_001]` (< 15 ký tự thực), hàm `_answer_from_evidence` sẽ tự động ghép nội dung trực tiếp từ các `EvidenceCandidate` để đảm bảo người dùng luôn nhận được thông tin chính xác.

---

### Khâu 9: Đối soát Sự thật, Ánh xạ Trích dẫn & Kiểm duyệt Đầu ra (Verification, Mapping & Output Guardrail)
- **Files đảm nhiệm**: `rag/verification.py`, `rag/mapper.py`, `guardrails/output.py`.
- **Cách xử lý**:
  1. **Fact Verification (`verify_answer` — chỉ chạy ở chế độ `strict`)**:
     - Tách câu trả lời thành từng mệnh đề/câu đơn (`_split_into_claims`), có bảo vệ các từ viết tắt hành chính (`UBND.`, `TP.`, `NĐ.`, `QĐ.`,...).
     - Lọc bỏ số thứ tự đầu dòng (`1. `, `2) `, `Bước 1:`) trước khi kiểm tra số liệu để không báo lỗi xung đột số liệu giả.
     - Kiểm tra từng mệnh đề qua 3 bộ lọc:
       - **Explicit Citation / Word Overlap**: Khi có mã `[EC_xxx]` hợp lệ, vẫn bắt buộc kiểm tra độ trùng lặp từ vựng (`>= 0.15`) để triệt tiêu hành vi trích dẫn vào câu bịa đặt; các câu không có mã phải đạt word overlap `>= 0.35` để được `supported`.
       - **Number Conflict Check (`_check_number_conflict`)**: Bóc tách mọi con số nội dung (lệ phí `50.000` -> `50000`, số ngày `03` -> `3`). Nếu câu trả lời xuất hiện con số nào **không tồn tại** trong văn bản bằng chứng gốc, mệnh đề đó lập tức bị đánh dấu `unsupported`.
       - **Negation Conflict Check (`_has_negation_conflict`)**: Phát hiện trường hợp câu trả lời khẳng định *"cần/phải/bắt buộc nộp X"* nhưng bằng chứng gốc lại ghi *"không cần / miễn / không bắt buộc X"*.
     - Nếu sau khi lọc, không có bất kỳ mệnh đề nào đạt trạng thái `supported`, hệ thống hủy câu trả lời của LLM và trả về thông báo `FALLBACK_TEXT` an toàn.
  2. **Citation Mapper (`map_verification_results`)**: Chuyển đổi các `VerificationResult` hợp lệ thành danh sách `VerifiedClaim` kèm thông tin `Citation` (`candidate_id`, `document_id`, `title`, `source`) để giao diện hiển thị các thẻ minh chứng (Evidence Chips).
  3. **Output Guardrail (`apply_output_guard`)**:
     - Che giấu (`[REDACTED_CCCD]`, `[REDACTED_PHONE]`) nếu LLM vô tình sinh ra số CCCD hoặc số điện thoại cá nhân không nằm trong văn bản pháp quy gốc (`allowed_text`).
     - Tự động đính kèm câu khuyến cáo pháp lý (`disclaimer`) ở cuối câu trả lời khi `effective_mode == "strict"`.

---

## 3. Công cụ & Công nghệ Sử dụng cho Từng Khâu (Technology Stack)

| Khâu xử lý | Công cụ / Thư viện / Công nghệ | Mô hình / Cấu hình chi tiết | File triển khai chính |
| :--- | :--- | :--- | :--- |
| **1. Giao diện (Frontend UI)** | **HTML5, CSS3, Vanilla JavaScript**, WebSocket API, Fetch API, Marked.js (render Markdown) | Giao diện Dark/Light mode, Sidebar quản lý 30 phiên, hiển thị Evidence Chips `[EC_xxx]` | `ui/web_ui.html`, `ui/static/js/app.js`, `ui/static/js/api.js` |
| **2. API Gateway & Giao thức** | **FastAPI**, **Uvicorn** (ASGI Server), **WebSocket**, **SSE (`StreamingResponse`)**, **Pydantic** | Port `8000`, hỗ trợ đồng thời WebSocket (`/ws/chat`) và HTTP SSE (`/api/chat`) | `backend/main.py`, `backend/api/chat.py`, `backend/api/socket.py`, `backend/api/sessions.py` |
| **3. Điều phối & Hàng đợi** | **Python `asyncio`** (`Semaphore`, `Lock`, `Queue`, `to_thread`) | `LLAMA_PARALLEL = 1`, khóa tuần tự theo từng `session_id` + Semaphore toàn cục | `backend/services/queue_service.py`, `backend/services/ai_service.py` |
| **4. Lưu trữ Phiên & Ngữ cảnh** | **PostgreSQL**, **SQLAlchemy 2.0 (AsyncEngine / `AsyncSessionLocal`)**, **`asyncpg`** | Lưu bảng `users`, `sessions`, `messages` (JSONB `evidence`); cơ chế `SLIM_CONTEXT` (20 messages gần nhất) | `context/database.py`, `context/models.py`, `context/context_service.py` |
| **5. Xử lý & Đánh chỉ mục Dữ liệu** | **Custom Python Loaders & FieldChunker**, **SHA-256 VersionTracker**, **Cosine Dedup** | Tách chunk theo trường (`_general`, `_docs`, `_fee`, `_time`, `_method`), `CHUNK_SIZE = 1400` | `ingestion/pipeline.py`, `ingestion/chunker.py`, `ingestion/dedup.py`, `ingestion/version.py` |
| **6. Mã hóa Vector (Embedding)** | **SentenceTransformers**, **PyTorch (`torch`)** | Mô hình **`BAAI/bge-m3`** (Dense Vector **1024 chiều**, chuẩn hóa L2, kèm LRU Cache 1000 câu) | `rag/retrieval.py`, `ingestion/embedder.py` |
| **7. Cơ sở dữ liệu Vector** | **Qdrant (`qdrant-client`)** | Hỗ trợ **Qdrant Cloud** hoặc **Qdrant Local On-disk** (`data/qdrant_db`), tìm kiếm Cosine + Metadata Filter | `rag/retrieval.py`, `ingestion/vector_store.py` |
| **8. Tổng hợp Câu hỏi (Synthesizer)** | **Rule-based Engine (Regex + Alias/Context Bypass)** kết hợp **`llama.cpp` (`llama-server`)** | Mặc định `SYNTHESIZER_MODE = "rule"`; LLM dự phòng: **`Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`** (Port `8081`, ctx `2048`) | `rag/synthesizer.py`, `rag/procedure_reader.py` |
| **9. Sinh Câu trả lời (Generator)** | **`llama.cpp` (`llama-server` OpenAI-compatible HTTP API)** + **Template Fast Path** | Mô hình **`Qwen2.5-3B-Instruct-Q4_K_M.gguf`** (Port `8080`, ctx `4096`, `threads=4`, `flash-attn=auto`, `cache-reuse=256`, `temp=0.0`) | `rag/generator.py`, `rag/pipeline.py`, `rag/prompt_builder.py` |
| **10. Kiểm chứng & Bảo mật** | **Python Regex (`re`)**, **Deterministic Heuristic Verifier** | Kiểm tra Prompt Injection, PII Redaction (CCCD/SĐT), Word-overlap (`>=0.35`), Number & Negation Conflict | `rag/verification.py`, `rag/mapper.py`, `guardrails/input.py`, `guardrails/output.py`, `guardrails/risk.py` |
| **11. Quản lý Đa miền (Multi-domain)** | **PyYAML**, **Python Dataclasses** | Cấu hình Zero-code qua `domains/<domain>/config.yaml` (`administrative_procedures`, `tourism_demo`, `cuisine_demo`) | `domains/domain_loader.py`, `domains/runtime.py`, `domains/schemas.py` |
| **12. Tích hợp Công cụ Ngoài (MCP)** | **FastAPI Mock/Real Tool Server**, **`httpx`**, **Circuit Breaker Pattern** | Tra cứu thủ tục trực tuyến / thời tiết (`lookup_official_procedure`, `get_weather`), timeout & retry breaker | `mcp/client.py`, `mcp/server.py`, `mcp/schemas.py` |
| **13. Đo kiểm & Đánh giá (Benchmark)** | **Custom Benchmark Runner**, **`httpx` SSE Client**, **`psutil`** | Đánh giá 4 suites: `Quality` (Doc Hit, Keyword Recall), `Rules`, `Latency` (TTFT, p50-p99), `Load & Soak` (RSS Memory) | `benchmark/run_benchmark.py`, `benchmark/suites/`, `eval_golden_set.py` |

---

## 4. Phân tích Những Điểm Yếu & Hạn chế Hiện tại của Hệ thống (System Weaknesses)

Dựa trên quá trình rà soát mã nguồn thực tế và phân tích đồ thị tri thức (`graphify-out/GRAPH_REPORT.md`), hệ thống hiện tại đang tồn tại **8 nhóm điểm yếu kỹ thuật lớn** cần lưu ý:

### 4.1. Nghẽn cổ chai Hiệu năng & Khả năng Chịu tải trên CPU (Concurrency & Throughput Bottleneck)
- **Giới hạn `LLAMA_PARALLEL = 1` và Semaphore toàn cục (`queue_service.py`)**:
  - Do chạy suy luận LLM cục bộ trên CPU (`threads = 4`), `QueueManager` đang khóa `asyncio.Semaphore(1)`. Điều này có nghĩa là **tại một thời điểm, toàn bộ hệ thống chỉ phục vụ được duy nhất 1 người dùng sinh câu trả lời**.
  - Nếu có 5–10 người dùng gửi câu hỏi cùng lúc (và không rơi vào Fast Path hay Cache), các request xếp sau phải đợi tuần tự (hiệu ứng *Head-of-Line Blocking*), khiến thời gian chờ (p95/p99 latency) tăng tuyến tính (có thể lên tới 15–40 giây).
- **Chưa tận dụng `asyncio` thực sự trong lõi RAG (`rag/pipeline.py`, `rag/generator.py`)**:
  - Toàn bộ hàm `answer_query()` và `stream_answer_3b()` được viết theo kiểu đồng bộ (synchronous) sử dụng thư viện `urllib.request` / `requests` và đẩy vào `asyncio.to_thread()`. Cách làm này tiêu tốn tài nguyên thread pool và không tối ưu bằng việc dùng `httpx.AsyncClient` bất đồng bộ xuyên suốt.

### 4.2. Khâu Reranker Đang là Placeholder & Chưa có Hybrid Search Chuẩn ở Tầng Vector DB
- **Reranker chưa có mô hình Cross-Encoder (`rag/rerank.py`)**:
  - Hàm `rerank(chunks)` hiện tại chỉ là một **placeholder** vỏn vẹn 1 lệnh `sorted(chunks, key=lambda c: c.retrieval_score, reverse=True)`. Hệ thống chưa có mô hình Cross-Encoder thực thụ (như `BAAI/bge-reranker-v2-m3`) để chấm điểm tương tác sâu giữa `(query, chunk)`.
- **Chỉ sử dụng Dense Vector của BGE-M3 (`rag/retrieval.py`)**:
  - Dù `BAAI/bge-m3` hỗ trợ đồng thời cả *Dense Vector*, *Sparse Vector (Lexical/BM25)* và *Multi-Vector (ColBERT)*, nhưng hiện tại hệ thống chỉ dùng `model.encode()` lấy Dense Vector 1024 chiều rồi tự bù đắp bằng các hàm cộng điểm từ khóa thủ công (`_calculate_keyword_bonus`, `_calculate_alias_bonus`).
  - Hệ quả: Nếu người dùng hỏi một thủ tục chưa được khai báo từ đồng nghĩa bình dân trong danh mục `aliases` của `procedures.json`, khả năng truy xuất chính xác sẽ giảm đáng kể.
- **Rủi ro "Được ăn cả, ngã về không" ở Two-Step Retrieval (`retrieve_two_step`)**:
  - Bước 1 chọn **duy nhất 1 `target_doc_id`** có điểm cao nhất rồi Bước 2 chỉ lấy các chunk của đúng `target_doc_id` đó. Nếu ở Bước 1 có 2 thủ tục rất giống nhau (ví dụ: *Đăng ký kết hôn* và *Cấp giấy xác nhận tình trạng hôn nhân*) và thủ tục đúng đứng Top 2 (chỉ kém Top 1 khoảng `0.01` điểm), toàn bộ thông tin của thủ tục đúng sẽ bị loại bỏ hoàn toàn ở Bước 2.

### 4.3. Hạn chế của Cơ chế Kiểm chứng Dựa trên Từ vựng & Regex (Verification Fragility)
- **Word Overlap không hiểu đồng nghĩa ngữ nghĩa (`rag/verification.py`)**:
  - Hàm `_calculate_word_overlap()` kiểm tra tỷ lệ giao nhau của tập từ (`claim_words.intersection(evidence_words)`). Nếu LLM **diễn đạt lại (paraphrase)** bằng từ đồng nghĩa (hoặc không gắn kèm nhãn `[EC_xxx]` ở câu đó) khiến tỷ lệ trùng từ rơi xuống `< 0.35`, câu trả lời dù đúng về mặt ý nghĩa vẫn bị đánh dấu là `unsupported` (False Negative).
  - Ngược lại, nếu LLM gắn đúng mã `[EC_001]` vào câu (`valid_explicit`), hàm `verify_answer()` gán thẳng `best_score = 1.0` mà **không kiểm tra lại độ trùng lặp từ vựng** (chỉ kiểm tra xung đột số liệu và phủ định). Nếu LLM trích dẫn `[EC_001]` nhưng bịa thêm một mệnh đề chữ (không chứa số và không chứa mẫu phủ định regex), mệnh đề đó vẫn lọt qua bộ lọc!
- **Kiểm tra Xung đột Số liệu (`_check_number_conflict`) quá cứng nhắc trong một số ngữ cảnh**:
  - Nếu mô hình tự đánh số thứ tự danh sách (`1.`, `2.`, `3.`) hoặc quy đổi đơn vị thời gian (ví dụ bằng chứng ghi *"trong ngày làm việc"*, LLM viết *"1 ngày làm việc"*), số `1`, `2`, `3` nếu không xuất hiện trong chunk bằng chứng sẽ khiến cả câu bị bác bỏ là `unsupported`.

### 4.4. Đánh đổi của Chế độ `SYNTHESIZER_MODE = "rule"` và `SLIM_CONTEXT`
- **Mất khả năng xử lý câu hỏi chuyển ý tinh tế ở lượt Follow-up**:
  - Với `SYNTHESIZER_MODE = "rule"`, hệ thống nối cứng câu hỏi mới với `active_procedure` của lượt trước (`"{query} (liên quan đến: {active_procedure})"`). Nếu ở lượt tiếp theo, người dùng hỏi sang một thủ tục mới bằng ngôn ngữ đời thường chưa có trong `entity_keywords` hay `aliases`, rule synthesizer sẽ ép câu hỏi mới đó gắn vào thủ tục cũ, dẫn đến truy xuất sai.
- **`derive_active_entity` phụ thuộc hoàn toàn vào Citation của lượt trước (`context/context_service.py`)**:
  - Khi bật `SLIM_CONTEXT = True`, hệ thống xác định thủ tục đang nói tới dựa trên `citations[0]["title"]` của câu trả lời trợ lý gần nhất. Nếu ở lượt 1 hệ thống trả về câu hỏi làm rõ (`clarification`) hoặc trả lời không có citation, thì sang lượt 2 `active_procedure` sẽ bị rỗng.
- **Đã tắt Tóm tắt Hội thoại & Bộ nhớ Dài hạn (`ENABLE_CONVERSATION_SUMMARY = False`, `ENABLE_LONG_TERM_MEMORY = False`)**:
  - Để tối ưu tốc độ trên CPU, các tính năng tóm tắt hội thoại dài và ghi nhớ thông tin người dùng qua nhiều phiên đã bị vô hiệu hóa. Các hội thoại kéo dài quá cửa sổ `HISTORY_PROMPT_TURNS = 2` (4 tin nhắn đưa vào prompt) sẽ mất ngữ cảnh của các lượt đầu tiên.

### 4.5. Bất đồng bộ Giữa Luồng WebSocket (`/ws/chat`) và REST SSE (`/api/chat`)
- **Multi-Intent chưa được tích hợp vào WebSocket (`backend/api/socket.py`)**:
  - Trong `backend/api/chat.py` (SSE), khi `MULTI_INTENT_ENABLED = True`, hệ thống gọi `answer_multi_stream()` và phát các sự kiện `section`.
  - Tuy nhiên, giao diện Web UI chính (`ui/static/js/app.js`) lại giao tiếp qua **WebSocket (`/ws/chat`)** trong `backend/api/socket.py` — nơi **chưa hề có nhánh xử lý `answer_multi_stream`** hay sự kiện `plan`/`section`. Do đó, tính năng tách câu hỏi đa ý định (Multi-intent) hiện chưa hoạt động đồng nhất trên giao diện WebSocket thời gian thực.

### 4.6. Hạn chế của Bộ nhớ Đệm Nội bộ (In-Memory State & Cache)
- **Cache nằm trong RAM của từng Process (`_PIPELINE_ANSWER_CACHE`, `_QUERY_EMBEDDING_CACHE`)**:
  - Cả bộ nhớ đệm câu trả lời (500 mục) và bộ nhớ đệm vector embedding (1000 mục) đều là biến `dict` toàn cục trong bộ nhớ Python, cơ chế xóa khi đầy là **FIFO** (`pop(next(iter(...)))`) chứ chưa phải chuẩn **LRU (Least Recently Used)** thực sự hay có **TTL (Time-To-Live)**.
  - Nếu khởi động lại server hoặc chạy nhiều Uvicorn workers (`--workers > 1`), cache không được chia sẻ giữa các worker (chưa dùng Redis) và việc dùng Qdrant Local (`path="data/qdrant_db"`) cũng sẽ gây lỗi khóa file (`file lock`) nếu chạy đa tiến trình.

### 4.7. Guardrails & Kiểm tra Địa điểm Dựa trên Regex Tĩnh (`guardrails/`, `rag/pipeline.py`)
- **Dễ bị lách qua (Bypass) hoặc Bắt nhầm (False Positive)**:
  - `INJECTION_PATTERNS` trong `guardrails/input.py` chỉ gồm 7 biểu thức chính quy cơ bản, rất dễ bị vượt qua bằng cách viết sai chính tả nhẹ, chèn ký tự đặc biệt hoặc dùng lối nói gián tiếp.
  - `_NON_HCMC_PATTERNS` trong `rag/pipeline.py` chặn cứng các tên tỉnh thành như *"Hà Nội"*, *"Bình Dương"*, *"Đà Nẵng"*. Nếu một công dân hỏi: *"Tôi hộ khẩu ở **Bình Dương** nhưng hiện đang tạm trú tại TP.HCM thì làm thủ tục đăng ký khai sinh ở TP.HCM cần gì?"*, hệ thống sẽ thấy chữ *"Bình Dương"* và **từ chối trả lời nhầm (False Positive)** dù thủ tục thực hiện tại TP.HCM.

### 4.8. Vấn đề Quản lý Mã nguồn & Độ gắn kết Module (Phát hiện từ Graphify)
- **Tồn đọng nhiều file lịch sử trong `.history/` làm nhiễu công cụ phân tích**:
  - Báo cáo `graphify-out/GRAPH_REPORT.md` cho thấy hàng trăm file bản sao trong `.history/` (như `prompt_builder_20260911...py`, `evidence_builder_20260914...py`) vẫn nằm trong thư mục làm việc, tạo ra 134 cạnh suy diễn trùng lặp quanh `EvidenceCandidate` và `build_prompt()`.
- **Một số module chưa được kết nối vào luồng chính (Isolated / Low-Cohesion Modules)**:
  - Module **`mcp/client.py` & `mcp/server.py`** (tích hợp công cụ tra cứu bên ngoài & thời tiết) và **`ingestion/loaders.py`** (PDF/DOCX/CSV/Web loaders) đã được xây dựng nhưng hiện tại chưa được nối trực tiếp vào luồng chat chính của `rag/pipeline.py`, dẫn đến các node bị cô lập (`APIEvidence`, `ContextObject`, `FinalResult`) và điểm gắn kết cộng đồng thấp (`Cohesion: 0.05` ở `client.py`).

---

## 5. Hướng dẫn Khởi chạy Nhanh (Quick Start)

> **Lưu ý môi trường**: Luôn sử dụng **`py -3.12`** trên máy hiện tại để đảm bảo đầy đủ các thư viện đã cài đặt.

```powershell
# 1. Nạp dữ liệu thủ tục hành chính vào Qdrant Vector DB (nếu chạy lần đầu)
py -3.12 -m ingestion.pipeline

# 2. Khởi động Backend Server (tự động bật FastAPI port 8000 + 2 tiến trình llama-server port 8080 & 8081)
py -3.12 backend/main.py

# 3. Chạy bộ đo kiểm Benchmark (Quality, Rules, Latency, Load)
py -3.12 benchmark/run_benchmark.py --domain administrative_procedures
```


<!-- AN_DOCS_START -->

## 6. Tổng quan hệ thống dành cho người dùng

**LLM Administrative Procedures** là hệ thống trợ lý AI sử dụng kiến trúc **Retrieval-Augmented Generation (RAG)** để hỗ trợ người dùng tra cứu thông tin **thủ tục hành chính tại TP. Hồ Chí Minh** bằng ngôn ngữ tự nhiên.

Hệ thống kết hợp:
- **FastAPI + Uvicorn** cho API và luồng streaming.
- **PostgreSQL** để lưu phiên, tin nhắn và ngữ cảnh hội thoại.
- **BAAI/bge-m3** để mã hóa câu hỏi thành vector 1024 chiều.
- **Qdrant** để tìm kiếm vector và dữ liệu theo domain.
- **Qwen2.5-1.5B** cho Query Synthesizer khi cần.
- **Qwen2.5-3B** cho sinh câu trả lời chính.
- **SSE / WebSocket** để trả kết quả theo thời gian thực.
- **Guardrails + Verification + Citation Mapping** để giảm câu trả lời không có căn cứ.

Hệ thống hiện hỗ trợ kiến trúc **Multi-domain**. Domain chính là `administrative_procedures` ở chế độ **Strict**; có thể mở rộng sang các domain khác như `tourism_demo` bằng cấu hình và dữ liệu mà không thay đổi pipeline RAG lõi.

### 6.1. Chức năng chính

- Tra cứu thủ tục hành chính bằng câu hỏi tự nhiên.
- Duy trì lịch sử và ngữ cảnh theo từng `session_id`.
- Truy xuất dữ liệu bằng BGE-M3 + Qdrant.
- Two-Step Retrieval để hạn chế trộn thông tin giữa các thủ tục.
- Hybrid scoring với alias, keyword, context bonus và negation penalty.
- Trả bằng chứng theo mã `[EC_xxx]`.
- Streaming câu trả lời bằng SSE hoặc WebSocket.
- Kiểm tra Prompt Injection và che dữ liệu nhạy cảm trong log.
- Kiểm tra phạm vi địa điểm hỗ trợ.
- Nạp dữ liệu JSON, CSV, XLSX, PDF và DOCX.
- Hỗ trợ thêm domain mới bằng cấu hình và dữ liệu.

### 6.2. Infographic kiến trúc hệ thống

![Infographic kiến trúc LLM Administrative Procedures](docs/images/system_architecture_infographic.svg)

> Infographic chỉ mô tả các thành phần đang có trong code hiện tại. Redis, CDN, Load Balancer, Kubernetes, Auto Scaling và vLLM không được mô tả như thành phần runtime hiện tại vì chưa được triển khai trong hệ thống.

---

## 7. Hướng dẫn sử dụng hệ thống

### 7.1. Chuẩn bị môi trường

Yêu cầu chính:
- Python + virtual environment của dự án.
- PostgreSQL theo `DATABASE_URL`.
- Model GGUF trong thư mục `model/`:
  - `Qwen2.5-3B-Instruct-Q4_K_M.gguf`
  - `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`
- Qdrant Cloud hoặc Qdrant Local.
- Dependency trong `requirements.txt`.

Tạo `.env` từ `.env.example` và cấu hình:

```env
DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname
DB_SSL=require
QDRANT_URL=https://your-qdrant-url
QDRANT_API_KEY=your_qdrant_api_key
DEFAULT_COLLECTION=administrative_procedures
```

### 7.2. Khởi động backend

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Khi khởi động, backend chuẩn bị PostgreSQL, BGE-M3, Qdrant, alias catalog và các `llama-server` cần thiết.

### 7.3. Truy cập Web UI

```text
http://127.0.0.1:8000
```

### 7.4. Tạo phiên hội thoại

Endpoint:

```text
GET /api/session/bootstrap
```

Hệ thống cấp `user_id` và `session_id` qua cookie `HttpOnly`.

### 7.5. Đặt câu hỏi

Ví dụ:

```text
Tôi muốn đăng ký kết hôn ở TP.HCM.
```

```text
Hồ sơ đăng ký khai sinh cần những giấy tờ gì?
```

Luồng chính:

```text
Người dùng
→ Web UI
→ FastAPI
→ Session Lock / Semaphore
→ Context PostgreSQL
→ Input Guard
→ Risk & Scope
→ Procedure Reader
→ Query Synthesizer
→ BGE-M3
→ Qdrant Retrieval
→ Rerank + Evidence
→ Template Fast Path hoặc Qwen2.5-3B
→ Verification + Output Guard
→ SSE / WebSocket
→ Người dùng
```

### 7.6. Câu hỏi tiếp theo

Trong cùng phiên có thể hỏi:

```text
Lệ phí bao nhiêu?
```

```text
Cần chuẩn bị giấy tờ gì?
```

```text
Nộp hồ sơ ở đâu?
```

Context Service dùng lịch sử PostgreSQL và `active_procedure` để duy trì mạch hội thoại.

### 7.7. Bằng chứng và trích dẫn

Các câu trả lời có thể kèm `[EC_001]`, `[EC_002]`... để liên kết với evidence đã retrieval.

### 7.8. REST SSE

Endpoint:

```text
POST /api/chat
```

Request mẫu:

```json
{
  "session_id": "<session-id>",
  "query": "Tôi muốn đăng ký kết hôn ở TP.HCM",
  "domain": "administrative_procedures"
}
```

Các event có thể gồm `chunk`, `evidence`, `clarification`, `done`.

### 7.9. WebSocket

Endpoint:

```text
/ws/chat
```

---

## 8. Luồng nạp dữ liệu (Ingestion)

```text
JSON / CSV / XLSX / PDF / DOCX
→ Loader
→ Validation
→ Chunking
→ Deduplication
→ Version Tracking
→ BGE-M3 Embedding
→ Qdrant
```

Đối với thủ tục hành chính, các nhóm chunk có thể gồm `_general`, `_docs`, `_fee`, `_time`, `_method`.

---

## 9. Kiến trúc triển khai hiện tại

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| Frontend | HTML5, CSS3, Vanilla JavaScript | Giao diện chat |
| Backend API | FastAPI, Uvicorn | REST, SSE, WebSocket |
| Điều phối | Python asyncio | Session lock, semaphore, queue |
| Context DB | PostgreSQL, SQLAlchemy, asyncpg | Phiên, tin nhắn, evidence, context |
| Embedding | SentenceTransformers, BGE-M3 | Vector 1024 chiều |
| Vector DB | Qdrant | Semantic retrieval |
| Synthesizer | Qwen2.5-1.5B + llama-server | Tổng hợp câu hỏi khi cần |
| Generator | Qwen2.5-3B + llama-server | Sinh câu trả lời |
| Guardrails | Python rules / regex | Input/output safety |
| Ingestion | Python loaders/chunker/dedup/versioning | Chuẩn hóa và lập chỉ mục |

### Chưa phải thành phần runtime hiện tại

- Redis
- CDN
- Load Balancer
- Kubernetes
- Auto Scaling
- vLLM
- S3/MinIO Object Storage

<!-- AN_DOCS_END -->
