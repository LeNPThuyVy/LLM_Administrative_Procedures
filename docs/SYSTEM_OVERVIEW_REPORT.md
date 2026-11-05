# BÁO CÁO TỔNG QUAN TOÀN HỆ THỐNG (SYSTEM OVERVIEW MASTER REPORT)

**Dự án:** LLM Administrative Procedures & Multi-Domain RAG Assistant
**Phạm vi:** Toàn bộ monorepo `LLM_Administrative_Procedures/` (2 phân hệ: `multi_domain_system`, `administrative_procedures_standalone`)
**Ngày tổng hợp:** 26/10/2026
**Nguồn tổng hợp:**
- `docs/AI_CORE_MULTI_DOMAIN_REPORT.md` — Báo cáo kỹ thuật Lõi AI đa domain (Nhóm AI/RAG Core, nhánh `feat/l2-b`, commit `303778a`)
- `docs/deploy_evaluation_report.md` — Báo cáo triển khai & đánh giá (Nguyễn Quốc An, số liệu đo trên `main` commit `034b965`, 22/10/2026)
- `docs/TestCase_He_Thong_KetQua_Updated.xlsx` — Bộ test case toàn hệ thống (9 sheet, ngày kiểm thử 26/10/2026)
- `Architecture_system.md`, `README.md`, `graphify-out/GRAPH_REPORT.md` (đồ thị tri thức, commit `939bf92a`)
- **Mã nguồn thực tế** (đã đối chiếu trực tiếp: `my_config.py`, `backend/`, `domains/`, `rag/`, `mcp_layer/`, `context/models.py`, `benchmark/config.yaml`, `data/`)

---

## 0. Hướng dẫn sử dụng tài liệu này (dành cho AI viết docs)

Tài liệu này là **nguồn sự thật duy nhất (single source of truth)** để sinh các tài liệu khác (README, API reference, hướng dẫn cài đặt, user guide, báo cáo đồ án, slide...). Khi sinh tài liệu, hãy tuân theo các quy tắc sau:

1. **Ưu tiên mã nguồn.** Khi các tài liệu cũ mâu thuẫn nhau, báo cáo này đã đối chiếu với code và ghi lại giá trị đúng. Xem **Mục 13 – Bảng đối chiếu sai lệch** trước khi trích dẫn bất kỳ con số nào từ README/Architecture cũ.
2. **Nhãn độ tin cậy** được dùng xuyên suốt:
   - `[CODE]` — đã xác minh trực tiếp trong mã nguồn hiện tại.
   - `[ĐO]` — số liệu đo thực nghiệm (luôn kèm thời điểm/commit/phiên test). Không được trình bày như benchmark tổng quát.
   - `[TÀI LIỆU]` — mô tả lấy từ tài liệu nội bộ, chưa xác minh độc lập trong code.
   - `[CẦN REVIEW]` — có dấu hiệu sai lệch/không nhất quán; không nên trích dẫn như sự thật.
3. **Không phóng đại.** Không dùng các con số marketing chưa có số đo hỗ trợ (ví dụ "hallucination < 1.5%", "Fast Path < 50ms", "1.298 thủ tục"). Xem Mục 13.
4. **Ngôn ngữ:** Tiếng Việt, giữ nguyên thuật ngữ kỹ thuật tiếng Anh (RAG, retrieval, rerank, streaming, TTFT...). Tên hàm/file/biến luôn đặt trong backtick.
5. **Máy chạy:** Windows, luôn dùng `py -3.12` khi viết lệnh mẫu.

---

## 1. Tổng quan dự án

### 1.1 Bài toán
Người dân và doanh nghiệp gặp khó khăn khi tra cứu thủ tục hành chính công (hồ sơ cần chuẩn bị, lệ phí, thời hạn, nơi nộp, hình thức nộp). Các chatbot LLM thông thường dựa vào tri thức tham số (parametric knowledge) nên dễ **ảo giác (hallucination)**, cung cấp thông tin lỗi thời và **không trích dẫn được nguồn**.

### 1.2 Giải pháp
Hệ thống trợ lý AI dạng **Retrieval-Augmented Generation (RAG)** chạy **hoàn toàn cục bộ trên CPU** (on-premise), kết hợp kiểm soát nhiều tầng:
- Chỉ trả lời dựa trên **bằng chứng truy xuất** (evidence) từ cơ sở tri thức, gắn trích dẫn `[EC_xxx]`.
- **Guardrails** đầu vào/đầu ra (chống prompt injection, che PII, phân loại rủi ro, chặn ngoài phạm vi địa lý/nghiệp vụ).
- **Verification** từng claim ở chế độ `strict` (kiểm tra số liệu, phủ định).
- **Template Fast Path** cho câu hỏi đơn trường (lệ phí/thời gian/hồ sơ/hình thức) — trả lời trực tiếp từ chunk, không gọi LLM sinh văn bản.
- **Kiến trúc đa domain**: cùng một lõi AI phục vụ nhiều lĩnh vực (thủ tục hành chính, ẩm thực, nấu ăn, du lịch) chỉ bằng file cấu hình YAML.
- **Streaming** câu trả lời theo thời gian thực qua WebSocket và SSE.

### 1.3 Phạm vi nghiệp vụ hiện tại
| Hạng mục | Giá trị | Nhãn |
|---|---|---|
| Domain chính | `administrative_procedures` — Thủ tục hành chính công **TP. Hồ Chí Minh** (cấp xã/phường, bộ phận một cửa) | `[CODE]` |
| Số thủ tục trong dữ liệu | **42 bản ghi** (`PROC_001` → `PROC_042`) trong `data/procedures.json` của **cả hai** phân hệ | `[CODE]` |
| Nhóm thủ tục | Hộ tịch (khai sinh, khai tử, kết hôn, nhận cha mẹ con, xác nhận tình trạng hôn nhân), chính sách xã hội & người có công, xây dựng – đất đai – nhà ở, hộ kinh doanh, giáo dục, lao động – việc làm, chứng thực | `[CODE]` |
| Thủ tục chưa có dữ liệu (ví dụ) | Đăng ký thường trú, hộ chiếu, visa, đổi giấy phép lái xe | `[CODE]`/`[ĐO]` |
| Domain phụ | `cuisine_demo` (20 món ăn), `cooking_recipe` (100 công thức, file `.xlsx`), `tourism_demo` (config còn, **dữ liệu nguồn không còn**) | `[CODE]` |

> Lưu ý: dữ liệu có một số thủ tục gần trùng lặp (ví dụ `PROC_009`/`PROC_023` khuyết tật; `PROC_011`/`PROC_015` thờ cúng liệt sĩ; `PROC_025`/`PROC_027` giấy phép xây dựng; `PROC_008`/`PROC_020` hưu trí xã hội; `PROC_014`/`PROC_019`; `PROC_010`/`PROC_016` hỏa táng). Điều này giải thích vì sao golden set chấp nhận nhiều `document_id` đúng cho cùng câu hỏi.

### 1.4 Đối tượng sử dụng
- Công dân tra cứu thủ tục; cán bộ một cửa cần tra cứu nhanh.
- Kỹ sư dữ liệu/nghiệp vụ: tạo domain mới, nạp dữ liệu qua Web UI.
- Kỹ sư AI: tối ưu pipeline, benchmark.

---

## 2. Kiến trúc Monorepo – 2 phân hệ

### 2.1 Bảng so sánh
| Tiêu chí | Phân hệ 1: `multi_domain_system/` | Phân hệ 2: `administrative_procedures_standalone/` |
|---|---|---|
| Mục đích | Nền tảng đa lĩnh vực, nghiên cứu & mở rộng | Bản đóng gói khép kín cho thủ tục hành chính TP.HCM |
| Cổng FastAPI mặc định `[CODE]` | **8002** (`SERVER_PORT`) — benchmark cấu hình gọi 8000 | **8003** (`STANDALONE_SERVER_PORT`) |
| Domain | `administrative_procedures`, `cuisine_demo`, `cooking_recipe`, `tourism_demo` + domain tạo động | Chỉ `administrative_procedures` |
| Dữ liệu thủ tục | 42 thủ tục | 42 thủ tục (cùng file, cùng kích thước) |
| Truy xuất | Dual-engine: Qdrant (vector) + Elasticsearch/Local BM25 (bảng) | Qdrant (vector) |
| Multi-intent, MCP | Có (`rag/multi/`, `mcp_layer/`) — multi-intent **tắt mặc định** | Không có thư mục `mcp_layer/`, `rag/multi/` |
| Benchmark, scripts, tests | `benchmark/`, `scripts/`, `tests_multi/`, `tests_tang1/`, `tests_tang2/` | Không có |
| Cookie phiên | `session_id`, `user_id` | `hcc_session_id`, `hcc_user_id` (mở song song 2 bản trên cùng trình duyệt không đè phiên) |
| Model GGUF | `multi_domain_system/model/` | `administrative_procedures_standalone/model/` (có thể override bằng `MODEL_DIR`, `LLM_3B_MODEL_PATH`, `LLM_1_5B_MODEL_PATH`) |
| llama-server | Tự khởi chạy 8080 (3B) & 8081 (1.5B); nếu cổng đã bận thì tái sử dụng | Tái sử dụng 8080/8081 nếu đang chạy, nếu không thì tự khởi chạy |
| UI | Đa domain: chọn domain, modal "Nạp dữ liệu" + "Tạo domain mới" | Cố định lĩnh vực, nút "📥 Cập nhật Dữ liệu Thủ tục Hành chính" |

### 2.2 Cây thư mục (đã xác minh)
```
LLM_Administrative_Procedures/
├── README.md, LICENSE (MIT), .gitignore
├── Architecture_system.md          # tài liệu kiến trúc nội bộ (gitignored)
├── docs/                           # báo cáo + test case Excel
├── graphify-out/                   # knowledge graph của codebase
├── task/                           # plan, summary, log (gitignored)
├── test/
├── multi_domain_system/
│   ├── backend/
│   │   ├── main.py                 # FastAPI app, lifespan, spawn llama-server, /health, /api/system/status
│   │   ├── api/  chat.py | sessions.py | socket.py | ingestion.py
│   │   └── services/  ai_service.py | context_service.py | queue_service.py
│   ├── domains/  domain_loader.py | runtime.py | <domain_id>/{config.yaml, schema.py, golden_set.json}
│   ├── rag/  pipeline.py | retrieval.py | rerank.py | synthesizer.py | generator.py | generation.py
│   │         prompt_builder.py | evidence_builder.py | verification.py | mapper.py
│   │         procedure_reader.py | history_reader.py | text_normalizer.py
│   │         multi/ {detector, orchestrator, resolver, section, title_index, cache, types}.py
│   ├── ingestion/ pipeline.py | ai_chunk_planner.py | chunker.py | dedup.py | embedder.py
│   │              vector_store.py | elastic_store.py | schema_validator.py | version_tracker.py
│   │              loaders/ {base, csv, docx, json, pdf, web}_loader.py
│   ├── context/  context_service.py | database.py | models.py | schemas.py | state.py | structured_context.py | init_db.py
│   ├── guardrails/ input.py | risk.py | output.py
│   ├── mcp_layer/ server.py | client.py | registry.py | bridge.py
│   ├── benchmark/ run_benchmark.py | config.yaml | README.md
│   ├── scripts/  eval_golden_set.py | calibrate_threshold.py | run_ingestion.py | backup_supabase_memory.py | cleanup_deprecated_tables.py
│   ├── tests_multi/ | tests_tang1/ | tests_tang2/
│   ├── ui/  web_ui.html | static/js/{app.js, api.js}
│   ├── data/ procedures.json | cuisine_demo.json | sources/ | qdrant_db/ | elastic_local/ | .ingestion_versions.json
│   ├── docs/ benchmark_latency_20261022.csv | eval_golden_set_administrative_procedures_20261022.json
│   ├── model/ Qwen2.5-3B-Instruct-Q4_K_M.gguf | Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
│   ├── my_config.py | requirements.txt | .env.example
└── administrative_procedures_standalone/
    ├── backend/ | domains/administrative_procedures/ | rag/ (cùng bộ file lõi, không có multi/)
    ├── ingestion/ | context/ | guardrails/ | ui/ | model/ | data/ | task/
    └── my_config.py | requirements.txt | .env.example
```

---

## 3. Tech stack & Môi trường

### 3.1 Công nghệ
| Tầng | Công nghệ | Vai trò |
|---|---|---|
| Ngôn ngữ | Python 3.12 | Toàn bộ backend/AI |
| API | FastAPI, Uvicorn, asyncio | REST, SSE, WebSocket |
| LLM Generator | Qwen2.5-3B-Instruct **GGUF Q4_K_M** | Sinh câu trả lời RAG; LLM Auto-Prompt khi ingest |
| LLM Synthesizer | Qwen2.5-1.5B-Instruct **GGUF Q4_K_M** | Viết lại/làm rõ truy vấn đa lượt (thường được bypass bằng rule) |
| Inference | llama.cpp `llama-server` (API tương thích OpenAI `/v1/chat/completions`) | Chạy GGUF trên CPU |
| Embedding | `BAAI/bge-m3` (SentenceTransformer, 1024 chiều, `max_seq_length=512`, `batch_size=32`) | Vector hóa truy vấn & tài liệu |
| Vector DB | Qdrant Cloud hoặc Qdrant Local (`data/qdrant_db`) | Dense retrieval (cosine) |
| Tabular search | Elasticsearch 8.x (`:9200`) hoặc **Local Okapi BM25** (`data/elastic_local/`) | Truy xuất dữ liệu bảng không cần embedding |
| Context DB | PostgreSQL (local hoặc Supabase) qua SQLAlchemy Async + asyncpg | Sessions, messages, evidence |
| Tool protocol | Model Context Protocol (`mcp`) | Công cụ ngoài (tra cứu thủ tục, thời tiết) |
| Ingestion | llama-index readers, openpyxl, docx2txt | Đọc PDF/DOCX/CSV/XLSX/Web |
| UI | HTML5 + Vanilla JS + CSS | SPA chat, không cần build |
| Test | pytest, pytest-asyncio | Unit/integration |

`requirements.txt` `[CODE]`: sentence-transformers, openai, python-dotenv, numpy, torch, transformers, sqlalchemy, asyncpg, fastapi, uvicorn[standard], pyyaml, httpx, mcp, pytest, pytest-asyncio, qdrant-client, FlagEmbedding, psycopg2-binary, openpyxl>=3.1.0, llama-index-core>=0.10.0, llama-index-readers-file, llama-index-readers-web, docx2txt>=0.9, elasticsearch>=8.0.0.

### 3.2 Môi trường kiểm thử `[ĐO]`
| Thông số | Giá trị |
|---|---|
| OS | Windows 11 (10.0.26300) |
| Python | 3.12.9 (`py -3.12`) |
| CPU | 4 nhân vật lý / 8 luồng, **không GPU** |
| RAM | 15.7 GB |
| Model 3B | ctx 4096, `--threads 4`, `--parallel 1`, `--flash-attn auto`, `--cache-reuse 256` |
| Model 1.5B | ctx 2048, threads = max(2, LLAMA_THREADS/2) |

### 3.3 Biến môi trường (`.env`) `[CODE]`
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `DATABASE_URL` | — | `postgresql+asyncpg://user:pass@host:5432/db` |
| `DB_SSL` | `require` (mẫu) | SSL cho Supabase |
| `QDRANT_URL`, `QDRANT_API_KEY` | rỗng → Qdrant Local | Kết nối Qdrant Cloud |
| `DEFAULT_COLLECTION` | `administrative_procedures` | Collection mặc định |
| `ELASTICSEARCH_URL`, `ELASTICSEARCH_API_KEY` | `http://127.0.0.1:9200` | Tabular search; offline → BM25 local |
| `LLAMA_THREADS` | 4 | Threads llama-server 3B |
| `LLAMA_PARALLEL` | 1 | Số slot song song / kích thước `_LLM_SEMAPHORE` |
| `LLAMA_CTX_SIZE` | 4096 | Context 3B |
| `LLAMA_BATCH_SIZE`, `LLAMA_UBATCH_SIZE` | 512 | Batch prefill |
| `SYNTHESIZER_MODE` | `rule` | `rule` (bypass LLM khi đủ thông tin) / `llm` / `off` |
| `MULTI_INTENT_ENABLED` | `False` | Bật tách câu hỏi nhiều thủ tục |
| `SLIM_CONTEXT` | `True` | Dùng `derive_active_entity` thay bảng `structured_context` |
| `ENABLE_LONG_TERM_MEMORY` | `False` | Bộ nhớ dài hạn (deprecated) |
| `ENABLE_CONVERSATION_SUMMARY` | `False` | Tóm tắt hội thoại (deprecated) |
| `HISTORY_STORE_TURNS` | 10 | Số lượt lưu/đọc (20 messages) |
| `HISTORY_PROMPT_TURNS` | 2 | Số lượt đưa vào prompt |
| `SERVER_HOST` / `SERVER_PORT` | `127.0.0.1` / `8002` | Phân hệ đa domain |
| `STANDALONE_SERVER_PORT` | `8003` | Phân hệ standalone |
| `MCP_SERVER_URL` | cổng mặc định 8001 | MCP server |

Hằng số khác `[CODE]`: `MAX_NEW_TOKENS = 512`; `_MAX_ANSWER_CACHE_SIZE = 500`; cổng LLM **hard-code** `8080` (3B) và `8081` (1.5B) trong `backend/main.py` và `rag/generator.py`.

---

## 4. Kiến trúc tổng thể

### 4.1 Sơ đồ thành phần
```mermaid
flowchart TD
    Client["Web UI / REST client"] -->|"WebSocket /ws/chat hoặc SSE POST /api/chat"| API["FastAPI Backend (8002 / 8003)"]
    API --> Queue["QueueManager: session lock + semaphore"]
    Queue --> Ctx["Context Service"]
    Ctx <--> PG[("PostgreSQL: sessions, messages, evidence")]
    Queue --> AISvc["AI Service (asyncio.to_thread)"]
    AISvc --> Pipe["RAG Pipeline (rag/pipeline.py)"]
    Pipe --> DR["Domain Runtime (domains/*.yaml)"]
    Pipe --> GIn["Input Guard + Risk Classifier"]
    GIn --> Syn["Synthesizer (rule / Qwen 1.5B :8081)"]
    Syn --> Ret["Dual-engine Retrieval"]
    Ret --> Qd[("Qdrant + BGE-M3")]
    Ret --> ES[("Elasticsearch / Local BM25")]
    Ret --> RR["N-gram Reranker + Evidence Builder"]
    RR --> FP{"Template Fast Path?"}
    FP -->|"Có"| GOut["Output Guard"]
    FP -->|"Không"| PB["Prompt Builder"]
    PB --> Gen["Generator Qwen 3B :8080"]
    Gen --> Ver["Verification + Mapper (strict)"]
    Ver --> GOut
    GOut -->|"token stream + evidence + done"| Client
    Pipe -.-> MCP["MCP Bridge / Client / Registry"]
    MCP -.-> MCPS["MCP Server :8001"]
```

### 4.2 Sequence diagram end-to-end
```mermaid
sequenceDiagram
    autonumber
    actor U as Người dùng
    participant API as Backend (WS/SSE)
    participant Ctx as Context (PostgreSQL)
    participant Core as RAG Pipeline
    participant Vec as Qdrant/BM25
    participant Gen as Qwen 3B
    U->>API: query + session_id + domain
    API->>Ctx: get_context(session_id, query)
    Ctx-->>API: recent_messages, active entity
    API->>Core: answer_question_stream(...)
    Core->>Core: normalize, validate_input, classify_risk, resolve_mode
    alt Câu chung chung / ngoài địa bàn / injection / rủi ro y tế
        Core-->>API: clarification hoặc từ chối (không gọi LLM)
    else Trúng Answer Cache
        Core-->>API: kết quả cache
    else Hợp lệ
        Core->>Core: synthesizer (rule bypass hoặc 1.5B)
        Core->>Vec: retrieve_two_step
        Vec-->>Core: RetrievedChunk[]
        Core->>Core: rerank + build_evidence_candidates (EC_xxx)
        alt Hỏi đúng 1 trường
            Core-->>API: Template Fast Path tokens
        else
            Core->>Gen: stream_answer_3b(prompt)
            Gen-->>Core: tokens
            Core->>Core: verify_answer + map + apply_output_guard
        end
        Core-->>API: chunk... evidence, done
    end
    API-->>U: stream
    API->>Ctx: update_memory (background task)
```

