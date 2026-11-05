# 🌐 Multi-Domain Intelligent Assistant Ecosystem (`multi_domain_system`)

> Phân hệ Trợ lý AI Đa lĩnh vực ứng dụng mô hình Ngôn ngữ Lớn (LLM), Kỹ thuật Truy vấn Lai Đa tầng (Hybrid Retrieval), Điều phối Đa ý định (Multi-Intent Orchestration) và Giao thức Model Context Protocol (MCP).

---

## 📖 Giới thiệu Phân hệ

`multi_domain_system` là nền tảng cốt lõi hỗ trợ đa lĩnh vực tri thức một cách linh hoạt. Hệ thống được trang bị cơ chế **Dynamic Domain Registry**, cho phép khai báo, cấu hình và nạp dữ liệu cho nhiều domain khác nhau mà không làm thay đổi kiến trúc mã nguồn.

### Các Domain Đã Tích Hợp Sẵn:
1. **`administrative_procedures`**: Hệ thống tra cứu và tư vấn 1.298 Thủ tục Hành chính Công TP.HCM.
2. **`cuisine_demo`**: Cơ sở dữ liệu và cẩm nang ẩm thực đặc sản Việt Nam.
3. **`cooking_recipe`**: Công thức nấu ăn và hướng dẫn chế biến 100 món ăn truyền thống.
4. **`tourism_demo`**: Hướng dẫn thông tin điểm đến và danh lam thắng cảnh du lịch.

---

## ✨ Điểm Nổi Bật Kỹ Thuật

- **🔍 Hybrid Retrieval & Re-ranking**: Kết hợp Dense Vector (`BAAI/bge-m3` trên Qdrant) với Lexical/BM25 (Elasticsearch 8.x) và bộ lọc đối soát reranking.
- **⚡ AI Chunk Planner**: Module phân tích cấu trúc tài liệu tự động (JSON, CSV, XLSX, PDF, DOCX, Web) để đề xuất chiến lược phân mảnh (chunking strategy) tối ưu nhất trước khi nạp vào Vector DB.
- **🎯 Multi-Intent Detection & Sub-query Orchestration**: Nhận diện câu hỏi đa ý định (ví dụ: vừa hỏi hồ sơ vừa hỏi lệ phí của 2 thủ tục khác nhau), tách thành các truy vấn con song song và tổng hợp câu trả lời hoàn chỉnh.
- **🧠 Quản lý Ngữ cảnh Đa lượt & Context Slimming**: Lưu trữ trạng thái hội thoại trên PostgreSQL (`AsyncPG`), tự động nén token ngữ cảnh (`SLIM_CONTEXT`) và trích xuất thực thể liên tục qua nhiều lượt trò chuyện.
- **🔌 Model Context Protocol (MCP)**: Tích hợp tầng công cụ mở rộng chuẩn hóa cho phép LLM tra cứu cơ sở dữ liệu chuyên ngành ngoại vi.
- **💻 Web UI Đa Domain Trực quan**: Giao diện SPA thuần hỗ trợ chọn domain động, tạo domain mới, xem trước kế hoạch chunking, tải lên tài liệu và chat streaming thời gian thực qua WebSocket.

---

## 📁 Cấu Trúc Thư Mục

```
multi_domain_system/
├── backend/                  # FastAPI web server & API routers (Port 8002)
│   ├── api/                  # Endpoints: chat, ingestion, sessions, socket
│   ├── services/             # AI service, Context service, Queue service
│   └── main.py               # Điểm khởi chạy FastAPI & Auto-spawn llama-server
├── domains/                  # Sổ đăng ký Domain động & Schemas
│   ├── administrative_procedures/ # Cấu hình domain thủ tục hành chính
│   ├── cooking_recipe/            # Cấu hình domain công thức nấu ăn
│   ├── cuisine_demo/              # Cấu hình domain ẩm thực
│   ├── tourism_demo/              # Cấu hình domain du lịch
│   └── domain_loader.py           # Nạp cấu hình domain từ file YAML
├── rag/                      # Pipeline RAG Đa domain
│   ├── multi/                # Bộ điều phối đa ý định (Detector, Orchestrator, Resolver)
│   ├── retrieval.py          # Tìm kiếm lai (Qdrant Dense + BM25)
│   ├── synthesizer.py        # Tái cấu trúc truy vấn (Qwen 1.5B)
│   ├── generator.py          # Lập luận sinh câu trả lời (Qwen 3B)
│   └── verification.py       # Đối soát dẫn chứng (Claim-Evidence Verifier)
├── ingestion/                # Pipeline nạp dữ liệu đa định dạng
│   ├── loaders/              # Loaders cho JSON, CSV, PDF, DOCX, Web
│   ├── ai_chunk_planner.py   # Lập kế hoạch phân mảnh thông minh
│   ├── chunker.py            # Phân mảnh ngữ nghĩa
│   ├── embedder.py           # Sinh vector nhúng BGE-M3 (Singleton)
│   ├── vector_store.py       # Quản lý Qdrant Vector DB
│   └── version_tracker.py    # Theo dõi phiên bản nạp bằng relative path hash
├── context/                  # Quản lý phiên và ngữ cảnh PostgreSQL
├── guardrails/               # Input filter, risk classifier & output sanitizer
├── mcp_layer/                # MCP Bridge, Client, Registry & Tools
├── model/                    # Thư mục lưu mô hình GGUF (3B và 1.5B)
├── data/                     # Dữ liệu nguồn, version JSON và local storage
├── ui/                       # Giao diện Web UI (HTML, CSS, JS)
├── benchmark/ & scripts/     # Bộ benchmark hiệu năng và script bảo trì
├── tests_*/                  # Bộ kiểm thử tự động
├── my_config.py              # File cấu hình tập trung phân hệ đa domain
└── requirements.txt          # Danh sách thư viện Python
```

---

## 🚀 Hướng Dẫn Khởi Chạy

### 1. Chuẩn Bị Môi Trường
```bash
cd multi_domain_system

# Tạo môi trường ảo với Python 3.12
py -3.12 -m venv .venv

# Kích hoạt môi trường ảo
# Trên Windows:
.venv\Scripts\activate
# Trên Linux/macOS:
source .venv/bin/activate

# Cài đặt thư viện
pip install -r requirements.txt
```

### 2. Tải Trọng Số Mô Hình GGUF
Đặt 2 file mô hình sau vào thư mục `multi_domain_system/model/`:
- `Qwen2.5-3B-Instruct-Q4_K_M.gguf` (~1.84 GB)
- `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf` (~940 MB)

### 3. Thiết Lập Biến Môi Trường
Sao chép `.env.example` thành `.env` và cập nhật thông số kết nối:
```bash
cp .env.example .env
```
Điền `DATABASE_URL` (PostgreSQL), `QDRANT_URL` và `QDRANT_API_KEY`.

### 4. Khởi Chạy Server
Hệ thống tích hợp sẵn tính năng **Auto-spawn `llama-server`** trong vòng đời (lifespan) của FastAPI. Bạn chỉ cần chạy lệnh sau:
```bash
py -3.12 backend/main.py
```
- Web UI sẽ sẵn sàng tại: **`http://127.0.0.1:8002`**
- API Documentation (Swagger): **`http://127.0.0.1:8002/docs`**

---

## 🛠️ Thêm Một Domain Mới

Hệ thống cho phép bổ sung domain mới qua 2 cách:
1. **Qua Web UI**: Mở Web UI tại `:8002` -> Bấm nút **"➕ Tạo Domain Mới"** -> Điền thông tin và tải lên file dữ liệu mẫu.
2. **Khai báo thủ công**:
   - Tạo thư mục `domains/<your_domain_id>/`.
   - Tạo file `config.yaml` định nghĩa schema, sources và prompt template.
   - Server sẽ tự động nhận diện domain mới mà không cần khởi động lại.
