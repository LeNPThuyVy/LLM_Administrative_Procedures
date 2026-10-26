# BÁO CÁO TRIỂN KHAI VÀ ĐÁNH GIÁ KẾT QUẢ HỆ THỐNG

**Dự án:** LLM Administrative Procedures  
**Phần thực hiện:** Triển khai hệ thống và đánh giá kết quả  
**Người thực hiện:** Nguyễn Quốc An  

---

## 1. Mục tiêu triển khai

Hệ thống LLM Administrative Procedures được xây dựng nhằm hỗ trợ người dùng tra cứu và hỏi đáp thông tin thủ tục hành chính bằng ngôn ngữ tự nhiên. Sau khi hoàn thiện các thành phần xử lý dữ liệu và AI Core, hệ thống cần được triển khai thành một ứng dụng có thể vận hành thực tế, tiếp nhận câu hỏi từ giao diện, quản lý phiên hội thoại, truy xuất dữ liệu, sinh câu trả lời và trả kết quả theo thời gian thực.

Phần triển khai tập trung vào việc kết nối các thành phần chính gồm FastAPI Backend, cơ sở dữ liệu PostgreSQL, Qdrant Vector Database, mô hình embedding BGE-M3 và hai mô hình Qwen2.5 chạy thông qua llama.cpp. Bên cạnh đó, hệ thống được đánh giá thông qua các phép kiểm thử API, retrieval, thời gian phản hồi, tài nguyên bộ nhớ và một số tình huống nghiệp vụ.

---

# 2. Môi trường triển khai

Hệ thống hiện được thiết kế để có thể chạy trên môi trường Windows hoặc Linux với Python 3.12. Trong quá trình phát triển và kiểm thử, hệ thống chủ yếu được vận hành trên máy tính cá nhân.

Các thành phần chính gồm:

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| Backend | FastAPI, Uvicorn | Cung cấp API và điều phối request |
| Giao diện | HTML, CSS, JavaScript | Giao diện chat cho người dùng |
| Context Database | PostgreSQL, SQLAlchemy, asyncpg | Lưu người dùng, phiên và lịch sử hội thoại |
| Vector Database | Qdrant | Lưu và truy xuất vector embedding |
| Embedding Model | BAAI/bge-m3 | Chuyển câu hỏi và dữ liệu thành vector 1024 chiều |
| LLM Generator | Qwen2.5-3B-Instruct Q4_K_M | Sinh câu trả lời chính |
| Query Synthesizer | Qwen2.5-1.5B-Instruct Q4_K_M | Tổng hợp và làm rõ truy vấn khi cần |
| Inference Engine | llama.cpp / llama-server | Chạy mô hình GGUF cục bộ |
| Tabular Search | Elasticsearch hoặc Local BM25 fallback | Hỗ trợ nhánh tìm kiếm dữ liệu CSV/XLSX |
| Streaming | SSE và WebSocket | Trả kết quả theo thời gian thực |

Các thông tin kết nối nhạy cảm như PostgreSQL hoặc Qdrant Cloud được cấu hình thông qua file `.env` và không được đưa trực tiếp lên GitHub.

---

# 3. Kiến trúc triển khai

Luồng xử lý tổng quát của hệ thống sau khi triển khai như sau:

```text
Người dùng
    ↓
Web UI
    ↓
FastAPI Backend
    ↓
Session Lock / Global Semaphore
    ↓
Context Manager
    ↕
PostgreSQL
    ↓
RAG Pipeline
    ↓
BGE-M3 Embedding
    ↓
Qdrant / Tabular Search
    ↓
Retrieval + Reranking + Evidence
    ↓
Qwen2.5 Generator
    ↓
Verification + Output Guard
    ↓
SSE / WebSocket
    ↓
Người dùng
```

Backend đóng vai trò trung tâm, nhận request từ người dùng và điều phối các thành phần còn lại.

---

## 3.1. FastAPI Backend

Backend được triển khai bằng FastAPI và Uvicorn.

Theo cấu hình hiện tại, server mặc định sử dụng:

```text
SERVER_HOST = 127.0.0.1
SERVER_PORT = 8002
```

Các endpoint quan trọng gồm:

```text
GET  /health
GET  /api/system/status
GET  /api/session/bootstrap
POST /api/chat
WS   /ws/chat
GET  /api/sessions/{id}/messages
```

Endpoint `/health` được sử dụng để kiểm tra backend còn hoạt động.

Endpoint `/api/system/status` cho biết trạng thái các thành phần:

- Database
- Embedding
- Vector Store
- LLM 3B
- LLM 1.5B

Khi tất cả thành phần đã sẵn sàng, hệ thống trả trạng thái `ready`.

---

## 3.2. Quản lý phiên và ngữ cảnh

Mỗi người dùng được gắn với một `user_id` và `session_id`.

Thông tin hội thoại được lưu trong PostgreSQL thông qua SQLAlchemy Async.

Các dữ liệu chính gồm:

- users;
- sessions;
- messages;
- evidence;
- lịch sử hội thoại.

Để tránh nhiều request của cùng một phiên được xử lý đồng thời gây sai ngữ cảnh, hệ thống sử dụng Session Lock.

Ngoài ra, Global Semaphore giới hạn số tiến trình suy luận LLM chạy đồng thời. Cấu hình mặc định:

```text
LLAMA_PARALLEL = 1
```

Cơ chế này phù hợp với môi trường máy cá nhân có tài nguyên giới hạn và giúp giảm tình trạng tranh chấp CPU khi nhiều request cùng gọi mô hình.

---

## 3.3. PostgreSQL

PostgreSQL được sử dụng để lưu dữ liệu ngữ cảnh hội thoại.

Chuỗi kết nối được lấy từ biến:

```text
DATABASE_URL
```

Ví dụ trong môi trường local:

```text
postgresql+asyncpg://postgres:postgres@localhost:5432/administrative_ai
```

Hệ thống sử dụng:

- SQLAlchemy AsyncEngine;
- AsyncSession;
- asyncpg.

Trong môi trường triển khai thực tế có thể sử dụng PostgreSQL trên cloud như Supabase thông qua cùng cấu trúc `DATABASE_URL`.

---

## 3.4. Vector Database Qdrant

Qdrant được sử dụng làm cơ sở dữ liệu vector chính cho các domain sử dụng semantic retrieval.

Hệ thống hỗ trợ hai chế độ:

**Qdrant Cloud**

```text
QDRANT_URL
QDRANT_API_KEY
```

hoặc **Qdrant Local** nếu không cấu hình URL cloud.

BGE-M3 chuyển câu hỏi thành vector 1024 chiều, sau đó Qdrant tìm các vector có độ tương đồng cao.

Việc sử dụng Qdrant giúp hệ thống không chỉ tìm kiếm theo từ khóa chính xác mà còn nhận diện được các câu hỏi có ý nghĩa tương tự với dữ liệu gốc.

---

## 3.5. Elasticsearch và dữ liệu dạng bảng

Phiên bản hiện tại có thêm nhánh xử lý dữ liệu dạng bảng như CSV và XLSX.

Cấu hình gồm:

```text
ELASTICSEARCH_URL
ELASTICSEARCH_API_KEY
```

Elasticsearch hoặc Local BM25 fallback được sử dụng cho các domain được cấu hình với backend tìm kiếm dạng bảng.

Như vậy, Elasticsearch không thay thế hoàn toàn Qdrant mà được sử dụng theo loại dữ liệu và cấu hình domain.

---

## 3.6. Embedding BGE-M3

Hệ thống sử dụng:

```text
BAAI/bge-m3
```

Embedding có kích thước:

```text
1024 dimensions
```

Model được nạp vào bộ nhớ trong quá trình khởi động hệ thống và được warm-up bằng một truy vấn mẫu.

Việc preload giúp tránh phải khởi tạo lại model cho từng request.

---

## 3.7. Triển khai hai mô hình Qwen2.5

Hệ thống sử dụng hai mô hình riêng cho hai nhiệm vụ.

### Qwen2.5-3B-Instruct

Được chạy tại:

```text
Port 8080
```

Vai trò chính là sinh câu trả lời cuối cùng.

Model sử dụng định dạng GGUF:

```text
Qwen2.5-3B-Instruct-Q4_K_M.gguf
```

### Qwen2.5-1.5B-Instruct

Được chạy tại:

```text
Port 8081
```

Model này hỗ trợ Query Synthesizer và các trường hợp cần làm rõ truy vấn.

File:

```text
Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
```

Cả hai model được chạy thông qua `llama-server` của llama.cpp.

Khi FastAPI khởi động, backend có thể tự khởi chạy hai tiến trình `llama-server`, kiểm tra health và gửi request warm-up.

---

# 4. Quy trình khởi động hệ thống

Một quy trình triển khai local có thể thực hiện như sau.

## Bước 1. Chuẩn bị virtual environment

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## Bước 2. Cài dependency

```powershell
pip install -r requirements.txt
```

## Bước 3. Cấu hình `.env`

Các cấu hình chính gồm:

```env
DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname
DB_SSL=true

QDRANT_URL=https://your-qdrant-url
QDRANT_API_KEY=your_qdrant_api_key

DEFAULT_COLLECTION=administrative_procedures
ELASTICSEARCH_URL=http://127.0.0.1:9200
```

## Bước 4. Chuẩn bị model

Các model GGUF được đặt trong thư mục:

```text
model/
```

gồm:

```text
Qwen2.5-3B-Instruct-Q4_K_M.gguf
Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
```

## Bước 5. Chạy backend

```powershell
py -3.12 backend\main.py
```

Sau khi khởi động có thể kiểm tra:

```text
http://127.0.0.1:8002/health
```

và:

```text
http://127.0.0.1:8002/api/system/status
```

---

# 5. Phương pháp đánh giá

Phần đánh giá được thực hiện trên hệ thống thật thông qua API, không dựa vào mock response.

Các nhóm đánh giá chính gồm:

1. Khả năng khởi động và health check.
2. Khả năng hoàn thành request qua HTTP/SSE.
3. Thời gian phản hồi.
4. Độ chính xác retrieval.
5. Tài nguyên RAM.
6. Khả năng xử lý câu hỏi ngoài phạm vi.
7. Kiểm tra evidence và verification.

Các số liệu thực nghiệm chính trong báo cáo này được thu thập trên phiên bản `main` commit `034b965` ngày 22/10/2026. Sau thời điểm đó, mã nguồn tiếp tục được cập nhật. Vì vậy, các số liệu này được sử dụng làm kết quả đánh giá thực nghiệm của phiên bản đã đo, không được hiểu là benchmark mới của commit hiện tại.

---

# 6. Kết quả kiểm tra trạng thái hệ thống

Các endpoint kiểm tra cơ bản cho kết quả:

```text
GET /health → status = ok
```

và:

```text
GET /api/system/status
```

đã ghi nhận trạng thái:

```text
status = ready
all_ready = true
```

Các thành phần:

- database;
- embedding;
- vector_store;
- llm_3b;
- llm_1_5b

đều được báo sẵn sàng trong lần đo.

Điều này xác nhận các dịch vụ nền đã khởi tạo, tuy nhiên không được xem là bằng chứng rằng mọi câu trả lời nghiệp vụ đều chính xác.

---

# 7. Đánh giá thời gian phản hồi

Một nhóm 5 request được chạy tuần tự qua:

```text
POST /api/chat
```

Mỗi request sử dụng một session riêng và kiểm tra HTTP 200 cùng sự kiện SSE `done`.

| STT | Câu hỏi | Thời gian |
|---:|---|---:|
| 1 | Đăng ký khai sinh cần hồ sơ gì? | 7,63 giây |
| 2 | Đăng ký kết hôn cần giấy tờ gì? | 3,78 giây |
| 3 | Lệ phí đăng ký khai sinh bao nhiêu? | 2,45 giây |
| 4 | Đăng ký hộ kinh doanh mất bao lâu? | 14,56 giây |
| 5 | Xin cấp số nhà cần những gì? | 11,98 giây |

Kết quả:

| Chỉ số | Giá trị |
|---|---:|
| Trung bình | 8,08 giây |
| Median p50 | 7,63 giây |
| Min | 2,45 giây |
| Max | 14,56 giây |
| p95 tham khảo | 14,04 giây |
| HTTP 200 + SSE done | 5/5 |

Do số lượng request chỉ có 5, p95 ở đây chỉ mang tính tham khảo.

---

# 8. Đánh giá mở rộng 12 request

Một đợt kiểm thử tiếp theo sử dụng 12 trường hợp thực tế qua API.

Các trường hợp bao gồm:

- câu hỏi thủ tục phổ biến;
- câu chào;
- câu ngoài phạm vi;
- câu ngoài địa bàn;
- prompt injection.

Kết quả:

| Chỉ số | Kết quả |
|---|---:|
| HTTP 200 + SSE done | 12/12 |
| Request lỗi | 0/12 |
| Thời gian trung bình | 3,281 giây |
| p50 | 1,928 giây |
| p95 | 8,500 giây |
| First SSE content p50 | 1,800 giây |
| First SSE content p95 | 4,648 giây |
| Ca có unsupported leak | 2/12 |
| Đúng document ID ở các ca được chấm | 7/7 |

Kết quả 12/12 không có lỗi request cho thấy backend hoạt động ổn định trong phạm vi bài test này.

Tuy nhiên, HTTP 200 và SSE `done` chỉ chứng minh request hoàn thành về mặt kỹ thuật, không chứng minh câu trả lời đúng hoàn toàn về nghiệp vụ hoặc pháp lý.

---

# 9. Đánh giá Retrieval

Golden set của domain thủ tục hành chính gồm:

```text
100 trường hợp
```

Trong đó:

```text
95 in-scope
5 out-of-scope
```

Kết quả:

| Chỉ số | Kết quả |
|---|---:|
| Retrieval@1 | 83/95 = 87,4% |
| Retrieval@3 | 88/95 = 92,6% |
| Retrieval@5 | 92/95 = 96,8% |
| MRR | 0,9042 |
| Field Match | 65/95 = 68,4% |
| Out-of-scope rejection | 1/5 = 20,0% |

Retrieval@5 đạt 96,8% cho thấy trong phần lớn câu hỏi hợp lệ, tài liệu mong đợi xuất hiện trong 5 kết quả đầu.

Tuy nhiên Field Match chỉ đạt 68,4%, cho thấy hệ thống vẫn cần cải thiện khả năng chọn đúng nhóm thông tin mà người dùng hỏi như:

- hồ sơ;
- lệ phí;
- thời gian;
- phương thức thực hiện.

Một hạn chế đáng chú ý là khả năng từ chối câu ngoài phạm vi ở tầng retrieval mới đạt 20% trên 5 ca out-of-scope của golden set.

---

# 10. Đánh giá RAM

Trong một lần đo Working Set bằng PowerShell, các tiến trình chính ghi nhận:

| Tiến trình | RAM quan sát |
|---|---:|
| llama-server 3B | khoảng 1.996,63 MB |
| llama-server 1.5B | khoảng 1.116,13 MB |
| Python lớn nhất | khoảng 2.065,16 MB |
| Các Python process khác | thấp hơn đáng kể |

Tổng số học ở thời điểm đo:

```text
5.237,97 MB
```

Trong bài kiểm thử 12 request, giá trị cao nhất ghi nhận theo từng PID gồm:

| Process | RAM lớn nhất quan sát |
|---|---:|
| llama-server | 2.111,77 MB |
| llama-server | 1.136,70 MB |
| python | 2.050,66 MB |

Tổng số học các đỉnh riêng lẻ là khoảng:

```text
5.390,70 MB
```

Tuy nhiên đây **không phải RAM peak đồng thời chính xác của hệ thống**, vì:

- các đỉnh xảy ra ở các thời điểm khác nhau;
- Working Set có thể chứa trang bộ nhớ chia sẻ;
- có thể có Python process không thuộc backend.

Vì vậy các giá trị này chỉ được dùng để tham khảo quy mô tài nguyên.

---

# 11. Đánh giá độ ổn định

Trong các bài kiểm thử API mở rộng:

```text
12/12 request
```

đều hoàn thành với HTTP 200 và SSE `done`.

Không ghi nhận request lỗi trong lần chạy đó.

Hệ thống cũng có cơ chế:

- health check;
- warm-up model;
- session lock;
- global semaphore;
- graceful cleanup llama-server.

Những cơ chế này giúp tăng tính ổn định khi vận hành trên môi trường tài nguyên hạn chế.

---

# 12. Các hạn chế phát hiện được

Qua kết quả kiểm thử, hệ thống vẫn còn một số điểm cần cải thiện.

## 12.1. Xử lý ngoài phạm vi

Out-of-scope rejection tại tầng retrieval chỉ đạt:

```text
1/5 = 20%
```

Điều này cho thấy scope gate hoặc threshold vẫn cần điều chỉnh.

## 12.2. Unsupported claim

Trong 12 request mở rộng:

```text
2/12
```

trường hợp vẫn xuất hiện nội dung bị verifier đánh dấu `unsupported`.

Cần kiểm tra bước verification và output filtering để đảm bảo các claim không đủ evidence không xuất hiện trong câu trả lời cuối.

## 12.3. Field Match

Field Match đạt:

```text
68,4%
```

thấp hơn Retrieval@5.

Điều này nghĩa là hệ thống thường tìm được đúng tài liệu nhưng chưa luôn chọn đúng phần thông tin mà người dùng cần.

## 12.4. Hiệu năng

Một số request mất trên 10 giây.

Ví dụ:

```text
14,56 giây
11,98 giây
```

Độ trễ phụ thuộc vào:

- retrieval;
- model generation;
- tình trạng cache;
- CPU;
- số lượng model đang chạy.

## 12.5. Tài nguyên

Hệ thống sử dụng đồng thời:

- BGE-M3;
- Qwen2.5-3B;
- Qwen2.5-1.5B;
- PostgreSQL;
- Qdrant;
- backend Python.

Với máy 8 GB RAM, tài nguyên có thể trở nên hạn chế khi chạy toàn bộ hệ thống cùng lúc.

---

# 13. Đánh giá tổng thể

Qua các bài kiểm thử đã thực hiện, hệ thống đã có khả năng triển khai và vận hành end-to-end:

```text
Người dùng
→ API
→ Context
→ Retrieval
→ AI Generation
→ Verification
→ Streaming Response
```

Các điểm tích cực gồm:

- Backend khởi động và health check thành công.
- Các thành phần AI và vector store có cơ chế warm-up.
- 12/12 request trong đợt kiểm thử mở rộng hoàn thành kỹ thuật.
- Retrieval@5 đạt 96,8%.
- Hệ thống hỗ trợ SSE và WebSocket.
- Có quản lý session và lịch sử hội thoại.
- Có evidence và verification.
- Có cơ chế xử lý nhiều domain và nhiều loại dữ liệu.

Tuy nhiên, chưa đủ cơ sở để kết luận hệ thống đã hoàn thiện ở mức production.

Các vấn đề cần ưu tiên gồm:

1. Cải thiện out-of-scope detection.
2. Ngăn unsupported claim xuất hiện trong output cuối.
3. Tăng Field Match.
4. Tối ưu latency trên CPU.
5. Đo lại RAM peak đồng thời bằng phương pháp chính xác hơn.
6. Thực hiện load test với nhiều người dùng.
7. Kiểm chứng nội dung pháp lý bằng chuyên gia hoặc nguồn chính thức.

---

# 14. Hướng phát triển

Trong các phiên bản tiếp theo, hệ thống có thể được cải tiến theo các hướng:

- triển khai backend lên server/cloud;
- sử dụng PostgreSQL và Qdrant Cloud ổn định;
- bổ sung reverse proxy HTTPS;
- xây dựng CI/CD;
- bổ sung monitoring;
- cải thiện hybrid retrieval;
- tối ưu concurrent inference;
- tăng bộ test multi-turn;
- mở rộng golden set;
- bổ sung regression test;
- kiểm chứng dữ liệu thủ tục theo nguồn chính thức;
- đánh giá trên phần cứng GPU;
- chạy benchmark client/server trên hai máy riêng biệt.

---

# 15. Kết luận

Phần triển khai đã kết nối thành công các thành phần Backend, Context Database, Vector Database, Embedding Model và LLM thành một hệ thống RAG hoàn chỉnh có khả năng xử lý câu hỏi theo thời gian thực.

Các kết quả kiểm thử thực nghiệm cho thấy hệ thống có khả năng vận hành ổn định ở mức demo và nghiên cứu. Retrieval cho kết quả tốt ở Top-5, các API có thể xử lý chuỗi request thực tế và hệ thống đã có các cơ chế kiểm soát evidence, session và streaming.

Tuy nhiên, một số vấn đề về ngoài phạm vi, unsupported claim, độ trễ và tiêu thụ tài nguyên vẫn cần được tiếp tục cải thiện trước khi triển khai ở môi trường production.

Các kết quả nêu trong phần đánh giá được lấy từ các lần kiểm thử đã thực hiện trên phiên bản được đo và không được xem là chứng nhận độ chính xác pháp lý tuyệt đối của hệ thống.