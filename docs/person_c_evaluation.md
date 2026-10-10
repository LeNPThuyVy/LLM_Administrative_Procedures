# Person C – Infrastructure & Evaluation Report

## 1. Mục tiêu

Person C phụ trách các phần liên quan đến:

- Infrastructure cho backend RAG.
- Streaming từ llama-server.
- Giới hạn tải và bảo vệ hệ thống khi quá tải.
- Health check các dependency.
- Logging có cấu trúc.
- Đánh giá hiệu năng bằng load test.
- Chuẩn bị bằng chứng để bàn giao và merge.

Các phần này được thực hiện trên branch:

```text
feat/c-infra-eval
```

---

## 2. True Streaming từ llama-server

Person C đã bổ sung true streaming tại:

```text
rag/generator.py
```

Streaming sử dụng endpoint:

```text
/v1/chat/completions
```

với chế độ:

```json
{
  "stream": true
}
```

### Kết quả kiểm tra

llama-server đã trả dữ liệu theo nhiều chunk liên tục thay vì phải chờ toàn bộ câu trả lời hoàn thành.

Ví dụ:

```text
Vi
ệt
 Nam
...
```

Kết quả: **PASS**

> Lưu ý: tầng generator đã có true streaming. Việc nối streaming thật vào `/api/chat` và `/ws/chat` đang chờ Person B cung cấp `answer_question_stream(...)`.

Person C không chỉnh sửa:

```text
rag/pipeline.py
```

để tránh conflict với phần việc của Person B.

---

## 3. Bounded Queue và Session Lock

Queue được cấu hình:

```text
max_concurrency = 3
max_queue_size = 12
queue_timeout = 30 giây
```

Ý nghĩa:

- Tối đa 3 request AI xử lý đồng thời.
- Tối đa 12 request chờ.
- Request vượt giới hạn queue bị từ chối.
- Request chờ quá lâu bị timeout.
- Session lock được cleanup sau khi không còn sử dụng.

### Kết quả kiểm tra

```text
Active slots occupied: 3
Waiting queue size: 12
OVERFLOW REQUEST: QueueFullError
```

Sau khi cleanup:

```text
Waiting count after cleanup: 0
PASS: Queue cleanup hoàn tất.
```

Kết quả: **PASS**

---

## 4. Rate Limiting

Rate limiting được áp dụng theo:

- `session_id`
- IP address

Cấu hình mặc định:

```text
Session: 20 request / 60 giây
IP: 60 request / 60 giây
```

### Kết quả test

```text
Request 01 - 20: HTTP 200
Request 21: HTTP 429
Request 22: HTTP 429
Request 23: HTTP 429
Request 24: HTTP 429
Request 25: HTTP 429
```

Kết quả tổng hợp:

```text
Total requests: 25
Status counts: {200: 20, 429: 5}
First 429 request: 21
Retry-After: 57
```

Kết quả: **PASS**

---

## 5. Health Check

Endpoint:

```text
GET /health
```

Health check kiểm tra trực tiếp:

- PostgreSQL Database
- Qdrant
- llama-server

Ví dụ kết quả:

```json
{
  "status": "ok",
  "dependencies": {
    "database": {
      "status": "ok"
    },
    "qdrant": {
      "status": "ok"
    },
    "llm": {
      "status": "ok"
    }
  }
}
```

Khi tất cả dependency hoạt động:

```text
HTTP 200
```

Nếu có dependency lỗi:

```text
HTTP 503
status = degraded
```

Kết quả: **PASS**

---

## 6. Structured Logging và Request ID

Backend đã bổ sung structured logging dạng JSON.

Mỗi HTTP request ghi lại:

- timestamp
- request_id
- method
- path
- status_code
- latency_ms

Ví dụ:

```json
{
  "event": "http_request",
  "request_id": "test-c-001",
  "method": "GET",
  "path": "/health",
  "status_code": 200,
  "latency_ms": 1681.63
}
```

Nếu client gửi:

```text
X-Request-ID: test-c-001
```

server trả lại đúng:

```text
x-request-id: test-c-001
```

Nếu client không gửi request ID, backend tự sinh UUID.

Logging không ghi:

- Query người dùng
- Cookie
- Token
- Authorization header
- Secret từ `.env`

Kết quả: **PASS**

---

## 7. WebSocket Logging

WebSocket hiện có:

- `connection_id` cho mỗi connection.
- `message_id` cho mỗi message.
- latency cho từng message.
- log connect/disconnect.
- log rate limit.
- log queue full.
- log queue timeout.
- log clarification.
- log xử lý thành công.

Không log trực tiếp nội dung câu hỏi của người dùng.

Kết quả: **PASS**

---

## 8. Retrieval Embedding Alignment

Retrieval đã được chỉnh để đọc:

```text
embedding_model
```

từ domain config.

Model được kiểm tra:

```text
BAAI/bge-m3
```

Kết quả encode:

```text
VECTOR_DIM: 1024
```

Điều này đảm bảo retrieval và ingestion sử dụng cùng embedding model.

Kết quả: **PASS**

---

## 9. CORS, Origin và Cookie Security

Đã bổ sung:

- CORS allowlist.
- WebSocket Origin validation.
- Cookie `httponly=True`.
- Cookie secure khi chạy HTTPS.
- `samesite="lax"`.

Allowed origin lấy từ:

```text
ALLOWED_ORIGINS
```

Kết quả: **PASS**

---

## 10. Load Test

Script sử dụng:

```text
scripts/load_test.py
```

Cấu hình:

```text
Total requests: 50
Concurrency: 10
Endpoint: /health
```

### Kết quả

```text
Success 200: 50
Server errors 5xx: 0
Network errors: 0
Error rate: 0.00%

p50 latency: 461.50 ms
p95 latency: 1782.56 ms
Average latency: 655.67 ms

Total time: 3.94 s
Throughput: 12.70 req/s
```

### Nhận xét

- 50/50 request thành công.
- Error rate = 0%.
- Không có HTTP 5xx.
- Không có network error.
- p50 = 461.50 ms.
- p95 = 1782.56 ms.
- Throughput = 12.70 request/giây.

Lưu ý: `/health` kiểm tra cả Database, Qdrant và LLM nên latency không chỉ phản ánh riêng FastAPI.

Kết quả: **PASS**

---

## 11. Tổng hợp Evaluation

| Hạng mục | Kết quả |
|---|---|
| Load test | 50 requests |
| Concurrency | 10 |
| Success | 50/50 |
| Error rate | 0.00% |
| HTTP 5xx | 0 |
| Network errors | 0 |
| p50 | 461.50 ms |
| p95 | 1782.56 ms |
| Throughput | 12.70 req/s |
| Session rate limit | 20 request / 60s |
| First HTTP 429 | Request 21 |
| Queue max concurrency | 3 |
| Queue max waiting | 12 |
| Queue overload | PASS |
| Queue cleanup | PASS |
| Database health | PASS |
| Qdrant health | PASS |
| LLM health | PASS |
| Request ID | PASS |
| Structured logging | PASS |

---

## 12. Các commit chính của Person C

```text
ce437b4 [C] add true llama server streaming
273e12f [C] bound queue and clean session locks
0b71bac [C] align retrieval embedder with domain config
f8f7cec [C] add session and IP rate limiting
ffe3ff1 [C] harden origin and secure cookies
4d87933 [C] add dependency health checks
3fc1f6f [C] add structured request logging
80d4999 [C] add load and overload evaluation scripts
```

---

## 13. Phần đang chờ Person B

True streaming tại tầng llama generator đã hoàn thành.

Tuy nhiên:

```text
/api/chat
/ws/chat
```

hiện vẫn đang sử dụng streaming giả ở tầng API.

Person C chờ Person B cung cấp:

```text
answer_question_stream(...)
```

Sau khi phần của Person B được merge, Person C mới nối true streaming vào chat và WebSocket.

---

## 14. Phần tạm hoãn

### Docker / Docker Compose

Tạm hoãn do giới hạn dung lượng ổ đĩa và tài nguyên máy local.

### Redis Cache

Redis là phần có thể cắt nếu thời gian hạn chế.

Ưu tiên hiện tại:

1. Streaming.
2. Queue.
3. Rate limiting.
4. Health check.
5. Structured logging.
6. Load testing.

---

## 15. Kết luận

Person C đã hoàn thành các phần chính về Infrastructure và Evaluation:

- True streaming từ llama-server.
- Bounded queue.
- Session lock cleanup.
- Retrieval embedding alignment.
- Rate limiting.
- CORS và Origin protection.
- Secure cookie.
- Health check Database/Qdrant/LLM.
- Structured logging.
- Request ID.
- Latency tracking.
- Load test.
- Rate limit test.
- Queue overload test.

Kết quả baseline:

```text
50/50 request thành công
Error rate: 0.00%
p50: 461.50 ms
p95: 1782.56 ms
Throughput: 12.70 req/s
```

Hệ thống cũng đã xác nhận hoạt động đúng khi quá tải:

```text
Rate limit → HTTP 429
Queue overflow → QueueFullError
Queue cleanup → 0
```

Phần còn phụ thuộc Person B là tích hợp true streaming từ pipeline vào hai endpoint chat.