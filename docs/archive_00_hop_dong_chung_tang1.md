# 00 – HỢP ĐỒNG CHUNG – Tầng 1 Domain Onboarding

> **Cả 3 người (A, B, C) và agent của mỗi người phải đọc file này trước khi code.**
> Đây là các interface đã chốt. **Không tự ý đổi.** Nếu cần đổi, báo cả nhóm rồi sửa file này trước.
> Tài liệu gốc để tham khảo code mẫu: `plan_tang1_domain_onboarding.md` (gọi tắt là "plan gốc", tham chiếu theo số Component).

## 1. Bối cảnh

- Dự án: Legal AI Assistant – hỏi đáp thủ tục hành chính (RAG). Dataset đầu tiên: thủ tục hành chính của phường (`data/procedures.json`).
- Hệ thống hiện tại **đã khá ổn**. Mục tiêu hôm nay: nâng **Tầng 1 (Domain Onboarding)** mà **không làm hỏng** phần AI Core đang chạy.
- Thay đổi chính: ChromaDB + MiniLM (384-dim) → **Qdrant Cloud + BGE-M3 (1024-dim)**; config theo từng domain (`domains/<id>/`); pipeline ETL mới (`ingestion/`).
- Yêu cầu mentor: (1) mở rộng được sang domain khác chỉ bằng cách thêm thư mục, (2) sẵn sàng deploy thực tế, (3) domain nghiêm túc (luật, sức khỏe) và domain thân thiện (du lịch, mua sắm) có `mode` khác nhau trong config.

## 2. Phân vai

| Vai | Phạm vi | Component (plan gốc) |
|---|---|---|
| **A – Data & Domain** | domains, loaders, validator, chunker, golden set | 2, 3, 4, 5 |
| **B – Embedding & Storage** (người có GPU) | embedder, Qdrant adapter, dedup, version tracker, pipeline, CLI | 1 (Qdrant/.env), 6, 7, 8, 9, 10, 11 |
| **C – Runtime & Eval** | migrate `rag/retrieval.py`, `my_config.py`, eval, regression | 12, 13, 1 (`my_config.py`) |

Quy ước tên: `A`, `B`, `C` ở các file plan tương ứng `plan_A_*.md`, `plan_B_*.md`, `plan_C_*.md`.

## 3. Git

- Nhánh: `feat/layer1-a`, `feat/layer1-b`, `feat/layer1-c`. **C là người merge cuối.**
- **Không xóa** `scripts/build_index.py`, `data/chroma_db/`, `data/procedures.json` trong ngày hôm nay.
- `requirements.txt`: mỗi người chỉ **thêm** dependency mình cần (không xóa dòng nào). C là người dọn `chromadb`/`sentence-transformers` ở bước cuối, khi đã ổn.
- Commit nhỏ, message dạng `[A] ...`, `[B] ...`, `[C] ...`.

## 4. Biến môi trường (`.env`) – B tạo và gửi cho A, C

```bash
QDRANT_URL=https://xxx.region.cloud.qdrant.io
QDRANT_API_KEY=...
```
Không commit `.env`. Gửi qua kênh riêng của nhóm.

## 5. Interface đã chốt

### 5.1 `Chunk` (A định nghĩa trong `ingestion/chunker.py`; B và C dùng)

```python
@dataclass
class Chunk:
    chunk_id: str      # vd "PROC_001_fee", "PROC_001_general"
    text: str          # nội dung dùng để embed VÀ lưu vào payload["text"]
    metadata: dict     # xem 5.2
```

Định dạng `text` cho chunk theo field (giữ như bản cũ):
```
Tên thủ tục: {title}
{label}:
{nội dung field}
```
Riêng chunk `general`: `text` = nội dung đầy đủ (`content`).

### 5.2 Payload Qdrant (B ghi, C đọc)

Mỗi point có `payload = {**chunk.metadata, "text": chunk.text}`. `metadata` **bắt buộc** có các key:

| Key | Ý nghĩa |
|---|---|
| `chunk_id` | giống `Chunk.chunk_id` |
| `document_id` | id thủ tục (vd `PROC_001`). **Tên key thống nhất toàn dự án.** Không dùng `proc_id`, `expected_proc_id`. |
| `title` | tên thủ tục |
| `domain` | `domain_id` (vd `administrative_procedures`) |
| `field` | `required_documents` / `fee` / `processing_time` / `submission_method` / `general` |
| `document_type`, `category`, `source_url` | như bản cũ, rỗng thì để `""` |

> **Việc đầu tiên của A và C:** mở `scripts/build_index.py` cũ, liệt kê **toàn bộ key metadata** mà Chroma đang lưu. Nếu bản cũ có key khác ngoài bảng trên mà `rag/*` đang dùng (ví dụ `procedure_name`, `agency`...), **thêm vào bảng này ngay** để không làm gãy `keyword_bonus`/`context_bonus`/`evidence_builder`. Điền kết quả vào mục 9 của file này.

Point id trong Qdrant: `uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id)` (như plan gốc).

### 5.3 Embedder (B định nghĩa trong `ingestion/embedder.py`; A, C dùng)

```python
class BGEEmbedder:
    def __init__(self, config: DomainConfig): ...
    def encode(self, texts: list[str]) -> list[list[float]]:
        """Trả về dense vector 1024 chiều, đã chuẩn hóa (L2 norm = 1)."""
```
- Model: `BAAI/bge-m3`, `max_length=512`, batch size cấu hình được (mặc định 12 trên CPU, 32 trên GPU).
- `use_fp16=True` **chỉ khi có CUDA**, ngược lại `False`.
- C dùng cùng embedder này cho query (không tự viết lại cách encode).

### 5.4 `DomainConfig` (A định nghĩa trong `domains/domain_loader.py`)

```python
@dataclass
class DomainConfig:
    domain_id: str
    domain_name: str
    description: str
    embedding_model: str            # "BAAI/bge-m3"
    embedding_dim: int              # 1024
    collection_name: str
    distance_metric: str            # "cosine"
    chunk_fields: list[str]
    chunk_field_specs: dict         # xem bên dưới
    sources: list[dict]
    mode: str                       # "strict" | "friendly"
    persona: str
    risk_level: str                 # "low" | "medium" | "high"
    dedup_threshold: float          # mặc định 0.95
```

`chunk_field_specs` nằm trong `config.yaml` (**không hardcode trong `chunker.py`**) để domain khác chỉ cần đổi yaml:

```yaml
chunk_field_specs:
  required_documents: { suffix: _docs,   label: "Thành phần hồ sơ" }
  fee:                { suffix: _fee,    label: "Lệ phí" }
  processing_time:    { suffix: _time,   label: "Thời gian giải quyết" }
  submission_method:  { suffix: _method, label: "Hình thức và nơi nộp hồ sơ", merge_with: [submission_location] }
  general:            { suffix: _general }
```

`load_domain_config()`: key thiếu trong yaml thì dùng default (không crash); key lạ thì bỏ qua và in cảnh báo.

### 5.5 Collection

| Tên | Mục đích | Ai tạo |
|---|---|---|
| `admin_dev` | collection **tạm**, chứa dữ liệu đổ từ Chroma cũ để C làm `retrieval.py` và eval khi pipeline chưa xong | C viết script, B chạy trên GPU |
| `administrative_procedures` | collection chính thức, do pipeline tạo | B |

Vector: size 1024, distance cosine. Tạo payload index cho `document_id` (keyword) và `field` (keyword).

### 5.6 Quy ước điểm số (C chịu trách nhiệm)

- `RetrievedChunk` giữ nguyên: `chunk_id, document_id, content, retrieval_score, metadata`. Consumer ở `rag/*` **không được sửa**.
- `retrieval_score`: **cao hơn = tốt hơn**.
- Qdrant cosine trả về *similarity* (cao = tốt), **không phải distance** như Chroma. Công thức cũ `1/(1+distance)` **phải bỏ**; dùng trực tiếp similarity (hoặc chuẩn hóa tương đương) rồi cộng `keyword_bonus`/`context_bonus` đã chỉnh lại.
- Dùng `client.query_points(...)` (API mới), không dùng `client.search` (deprecated).

### 5.7 Golden set (A tạo, C dùng)

File: `domains/administrative_procedures/golden_set.json`

```json
[
  {
    "id": "GS_001",
    "question": "Lệ phí đăng ký kết hôn là bao nhiêu?",
    "expected_document_id": "PROC_001",
    "expected_field": "fee",
    "expected_keywords": ["lệ phí"]
  }
]
```
- Tên key: `expected_document_id` (không phải `expected_proc_id`), `expected_field` (không phải `expected_chunk_suffix`).
- `expected_field` và `expected_keywords` là tùy chọn.
- `expected_document_id` phải tồn tại trong dữ liệu.

## 6. Mốc bàn giao giữa các vai (giờ tính từ lúc bắt đầu)

| Mốc | Ai → Ai | Bàn giao | Cách kiểm tra |
|---|---|---|---|
| 0:30 | B → A, C | Qdrant URL/key, cache model BGE-M3 | Cả nhóm kết nối được Qdrant |
| 1:30 | A → B, C | `domain_loader.py` + `config.yaml` + mục 9 điền xong | `load_domain_config("administrative_procedures")` chạy |
| 2:00 | B → C | `embedder.py` + `vector_store.py` chạy được | Upsert/search vài chunk giả |
| 2:15 | C → B | Script `scripts/tmp_chroma_to_qdrant.py` | B chạy trên GPU, tạo `admin_dev` |
| 3:00 | B → C | `admin_dev` đã có dữ liệu | C test `retrieve()` thật |
| 3:30 | A → B | `chunker.py` chạy với JSON thật | Số chunk khớp bản cũ |
| 5:00 | A → C | `golden_set.json` (tối thiểu 30 câu) | C chạy `eval_golden_set.py` |
| 5:30 | B → C | Collection `administrative_procedures` chính thức | Điểm points = chunk sau dedup |

Nếu trễ mốc nào thì báo ngay trong kênh nhóm, người nhận dùng mock/dữ liệu tạm để tiếp tục.

## 7. Bước tích hợp (5:30–7:00, cả nhóm)

1. C đổi retrieval sang `administrative_procedures`.
2. C chạy: `eval_golden_set.py`, `test/eval_fast.py`, smoke test "Hồ sơ đăng ký kết hôn cần những gì?".
3. A, B sửa theo danh sách câu sai C đưa.
4. Khởi động `backend/main.py`, thử `/ws/chat`.
5. C dọn `requirements.txt`.

## 8. Điều kiện "xong hôm nay" (Definition of Done)

- [ ] `python scripts/run_ingestion.py --domain administrative_procedures --force` chạy sạch, collection có vector size 1024
- [ ] `retrieve()` và `retrieve_two_step()` chạy trên Qdrant, `backend/main.py` khởi động và chat được
- [ ] Retrieval@5 trên golden set có số liệu; mục tiêu ≥ 80% và không thấp hơn baseline `eval_fast.py` cũ đáng kể
- [ ] 5 loader (JSON, CSV, PDF, DOCX, web) chạy được với file mẫu
- [ ] Chroma và `build_index.py` vẫn còn nguyên

Có thể trượt sang ngày mai: tinh chỉnh trọng số score, golden set đủ 50 câu, loader PDF/web với dữ liệu thật, dọn dependency cũ.

## 9. Metadata keys thực tế của bản cũ (A + C điền ở 0:30–1:30)

> Liệt kê key metadata mà `scripts/build_index.py` đang ghi vào Chroma và key mà `rag/*` đang đọc. Điền vào đây rồi thông báo nhóm.

```
- document_id (mã thủ tục, ví dụ PROC_001)
- title (tiêu đề thủ tục)
- document_type (loại văn bản)
- category (danh mục)
- source_url (link nguồn)
- chunk_id (mã chunk, ví dụ PROC_001_docs, PROC_001_general)
- field (tên field: required_documents, fee, processing_time, submission_method, general)
- page (evidence_builder.py đọc)
- location (retrieval.py đọc trong calculation bonus)
- procedure_name (retrieval.py đọc trong calculation bonus)
```

## 10. Nguyên tắc cho agent

- Chỉ sửa file thuộc phạm vi của mình (xem bảng phân vai). Cần sửa file của người khác thì báo trong nhóm.
- Không đổi tên hàm/class đã nêu trong mục 5.
- Mọi khác biệt so với plan gốc đã được ghi trong các file `plan_A/B/C`; khi plan gốc và các file này mâu thuẫn, **các file này thắng**.
- Không xóa dữ liệu hoặc file cũ. Không commit `.env`.
