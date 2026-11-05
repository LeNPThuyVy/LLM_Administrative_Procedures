# 🏛️ Standalone Administrative Procedures Assistant (`administrative_procedures_standalone`)

> Phiên bản Độc lập 100% Chuyên biệt hóa cho 1.298 Thủ tục Hành chính Công TP.HCM (Strict Mode), tối ưu hóa độ trễ cực thấp với Template Fast Path, không phụ thuộc thư mục ngoài và có thể đóng gói/triển khai độc lập trên bất kỳ máy chủ nào.

---

## 📖 Giới thiệu Phân hệ

`administrative_procedures_standalone` là giải pháp RAG chuyên sâu được đóng gói hoàn toàn khép kín để giải quyết bài toán tư vấn thủ tục hành chính công tại Việt Nam.

Phân hệ này vận hành ở chế độ **Nghiêm ngặt (Strict Mode)**:
- Chỉ tiếp nhận và phản hồi các thắc mắc liên quan trực tiếp đến 1.298 thủ tục hành chính đã được chuẩn hóa trong cơ sở dữ liệu (`data/procedures.json`).
- Mọi câu hỏi ngoài phạm vi thủ tục công sẽ được Input Guardrail từ chối lịch sự để đảm bảo tính an toàn và chuẩn mực pháp lý.

---

## ✨ Điểm Nổi Bật Kỹ Thuật

- **⚡ Template Fast Path (<50ms)**: Với các câu hỏi đơn trường phổ biến (ví dụ: *"lệ phí làm thủ tục X là bao nhiêu?"*, *"thời hạn giải quyết bao lâu?"*, *"nộp hồ sơ ở cơ quan nào?"*), hệ thống kích hoạt Fast Path trích xuất trực tiếp từ cấu trúc dữ liệu đã lập chỉ mục và phản hồi tức thì mà **không cần gọi qua LLM**, tiết kiệm 100% chi phí tính toán và loại trừ hoàn toàn nguy cơ ảo giác.
- **🛡️ Bộ Lọc An Toàn 3 Tầng**:
  - *Input Guardrail*: Nhận diện prompt injection, kiểm tra phạm vi địa bàn và lĩnh vực hành chính.
  - *Legal Risk Assessment*: Đánh giá mức độ rủi ro của câu hỏi (thủ tục nhạy cảm, tranh chấp, khiếu nại).
  - *Output Claim Verification*: Đối soát từng luận điểm câu trả lời với căn cứ pháp lý trong hồ sơ trước khi gửi tới công dân.
- **📦 Hoàn Toàn Độc Lập (Self-Contained)**:
  - Sở hữu thư mục mô hình riêng (`model/`), cấu hình riêng (`my_config.py`), danh mục thư viện riêng (`requirements.txt`).
  - Toàn bộ cơ chế theo dõi phiên bản (`.ingestion_versions.json`) sử dụng đường dẫn tương đối (relative path), cho phép sao chép hoặc nén folder sang bất kỳ máy tính/ổ đĩa nào là chạy được ngay.
- **🔌 Quản Lý Tiến Trình Tự Động**: Tích hợp sẵn cơ chế Auto-spawn 2 tiến trình `llama-server` (Qwen 3B tại cổng `8080` và Qwen 1.5B tại cổng `8081`) khi khởi động backend.
- **💻 Giao Diện Web UI Chuyên Biệt**: Web UI SPA tại cổng `8003` được tinh giản riêng cho tác vụ tra cứu thủ tục công, có sẵn nút nạp/cập nhật dữ liệu thủ tục và theo dõi tiến độ thời gian thực.

---

## 📁 Cấu Trúc Thư Mục

```
administrative_procedures_standalone/
├── backend/                  # FastAPI web server & API routers (Port 8003)
│   ├── api/                  # Endpoints: chat, ingestion, sessions, socket
│   ├── services/             # AI service, Context service, Queue service
│   └── main.py               # Điểm khởi chạy FastAPI & Auto-spawn llama-server
├── domains/                  # Domain duy nhất: administrative_procedures
│   └── administrative_procedures/ # Schema & cấu hình thủ tục hành chính
├── rag/                      # Pipeline RAG chuyên biệt
│   ├── retrieval.py          # Tìm kiếm hybrid trên Qdrant Cloud / Local
│   ├── synthesizer.py        # Tái cấu trúc truy vấn (Qwen 1.5B)
│   ├── generator.py          # Sinh câu trả lời RAG (Qwen 3B)
│   ├── verification.py       # Đối soát căn cứ pháp lý
│   └── prompt_builder.py     # Lắp ráp prompt dẫn chứng hồ sơ thủ tục
├── ingestion/                # Pipeline nạp dữ liệu thủ tục
│   ├── loaders/              # Loaders hỗ trợ JSON, CSV, PDF, DOCX, Web
│   ├── chunker.py            # Phân đoạn ngữ nghĩa thủ tục
│   ├── embedder.py           # Sinh vector nhúng BGE-M3 (Singleton tối ưu RAM)
│   ├── vector_store.py       # Quản lý Qdrant Vector DB
│   └── version_tracker.py    # Theo dõi phiên bản MD5 bằng relative path
├── context/                  # Quản lý phiên hội thoại & lưu trữ PostgreSQL
├── guardrails/               # Input guardrails, Risk assessment & Output verification
├── model/                    # Thư mục lưu 2 mô hình GGUF (3B và 1.5B)
├── data/                     # procedures.json (1.298 thủ tục) & .ingestion_versions.json
├── ui/                       # Giao diện Web UI chuyên biệt
├── my_config.py              # File cấu hình độc lập phân hệ
├── requirements.txt          # Danh sách thư viện Python phụ thuộc
├── .env.example              # Mẫu cấu hình biến môi trường
└── .gitignore                # Cấu hình bỏ qua Git nội bộ
```

---

## 🚀 Hướng Dẫn Khởi Chạy

### 1. Chuẩn Bị Môi Trường
```bash
cd administrative_procedures_standalone

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

### 2. Mô Hình GGUF Cục Bộ
Đảm bảo 2 file mô hình đã có sẵn trong thư mục `administrative_procedures_standalone/model/`:
- `Qwen2.5-3B-Instruct-Q4_K_M.gguf` (~1.84 GB)
- `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf` (~940 MB)

### 3. Thiết Lập Biến Môi Trường
Sao chép `.env.example` thành `.env` và cập nhật thông số kết nối:
```bash
cp .env.example .env
```
Điền `DATABASE_URL` (PostgreSQL), `QDRANT_URL` và `QDRANT_API_KEY`.

### 4. Khởi Chạy Server
```bash
py -3.12 backend/main.py
```
- Web UI chuyên biệt: **`http://127.0.0.1:8003`**
- API Documentation (Swagger): **`http://127.0.0.1:8003/docs`**
- Hai mô hình `llama-server` (Qwen 3B `:8080` và Qwen 1.5B `:8081`) sẽ được khởi động tự động.
