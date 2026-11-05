# BÁO CÁO CẢI TIẾN TỔ CHỨC MÃ NGUỒN VÀ ĐỘ TIN CẬY HỆ THỐNG
**Project:** LLM Administrative Procedures & Multi-Domain System  
**Branch:** `feat/l2-b`  
**Ngày thực hiện:** 05/11/2026  
**Mục tiêu:** Khắc phục triệt để "Lỗi 5 – Tổ chức code chưa tốt như tài liệu mô tả" mà bảo toàn 100% chức năng AI/RAG, streaming, guardrails và multi-turn context.

---

## 1. Vấn đề ban đầu
1. **File `rag/pipeline.py` quá dài (1.046 dòng) và gánh quá nhiều trách nhiệm:**
   - Ôm đồm cả khâu lọc early guard, chuẩn hóa chuỗi tiếng Việt, kiểm duyệt rủi ro, template fast path, cache, MCP tool bridging, retrieval, rerank, generation, streaming worker thread và verification.
2. **API Controller và Business Logic gắn chặt (Tight Coupling):**
   - Các file controller như `backend/api/chat.py` (200 dòng) và `backend/api/socket.py` (516 dòng) trực tiếp ôm logic phân loại truy vấn, quản lý lock/semaphore, định dạng dữ liệu SSE/WebSocket, chia nhánh đa ý định và khởi tạo memory update.
3. **Background Memory Update thiếu độ tin cậy:**
   - Các tác vụ lưu trữ lịch sử và ngữ cảnh hội thoại (`update_memory`) được gọi trực tiếp bằng `asyncio.create_task()` theo cơ chế fire-and-forget, không có retry khi gặp lỗi tạm thời (transient DB failure/lock timeout), không có supervisor theo dõi vòng đời tác vụ và có nguy cơ nuốt lỗi âm thầm.
4. **Xử lý ngoại lệ còn nhiều `except Exception: pass`:**
   - Nuốt lỗi hoặc fallback âm thầm khiến hệ thống trông như thành công dù xảy ra sự cố nội bộ.
5. **Logging phụ thuộc lệnh `print()` thô:**
   - Gây nhiễu stdout/stderr, thiếu structured context và không phân cấp mức độ nghiêm trọng (`DEBUG`, `INFO`, `WARNING`, `ERROR`).
6. **Dependencies chưa khóa phiên bản nhất quán:**
   - `requirements.txt` để phiên bản mở (unpinned), có nguy cơ vỡ môi trường khi cài đặt lại ở thời điểm khác.
7. **Bộ Benchmark thiếu module `benchmark.lib`:**
   - File `benchmark/run_benchmark.py` và các test suites import `benchmark.lib` nhưng thư mục này không tồn tại trong repo, làm tê liệt khả năng chạy đánh giá SLO độc lập.

---

## 2. Root Cause
- **`rag/pipeline.py` tích tụ theo thời gian:** Mỗi lần bổ sung tính năng mới (Template Fast Path, Strict Mode, Ambiguous Check, Medical Safety Guard), code được viết nối tiếp vào `pipeline.py` thay vì bóc tách theo nguyên lý Single Responsibility Principle (SRP).
- **Controller quá dày:** Do ban đầu chưa có tầng Service trung gian (`chat_service.py`), mã điều phối luồng streaming và xử lý SSE/WebSocket được viết trực tiếp bên trong route function của FastAPI.
- **Background task chưa được phòng vệ:** Sử dụng `asyncio.create_task()` mà không có lớp bọc xử lý lỗi và cơ chế retry có giới hạn (exponential backoff).
- **Nguyên nhân cốt lõi mất `benchmark.lib`:** File `.gitignore` có quy tắc `lib/` không neo (unanchored rule), khiến Git tự động bỏ qua toàn bộ thư mục `benchmark/lib/`. Khi tác giả commit benchmark ở commit `157ca05`, thư mục `lib/` bị Git loại trừ âm thầm mà không được đẩy lên remote. Ngoài ra, file `selftest/mock_server.py` trỏ sai đường dẫn golden set cũ (`tourism_demo` thay vì `cuisine_demo`).

---

## 3. Thay đổi kiến trúc

### Sơ đồ luồng phân tầng mới
```
Client (HTTP/SSE / WebSocket)
   │
   ▼
Transport Controllers (backend/api/chat.py, socket.py)
   │ (Thin: parse request, validate input, serialize events)
   ▼
Domain & Chat Services (backend/services/chat_service.py, ai_service.py)
   │ (Orchestration, Queue concurrency, SSE formatting)
   ├───────────────────────────────┐
   ▼                               ▼
AI Core Pipeline (rag/pipeline.py)   Background Task Supervisor (backend/services/background_tasks.py)
   │                               │ (Bounded retries, Exponential backoff, Error logging)
   ├─ pipeline_guards.py           ▼
   ├─ pipeline_cache.py          Memory & Context Persistence (context/context_service.py)
   ├─ pipeline_fast_path.py
   ├─ pipeline_tools.py
   └─ streaming.py
```

- **Tách biệt rõ rệt giữa Transport và Domain Logic:** Endpoints trong `backend/api/chat.py` giờ chỉ dày ~35 dòng, hoàn toàn đóng vai trò tiếp nhận HTTP/SSE và chuyển giao cho `chat_service.py`.
- **Pipeline Orchestrator tinh gọn:** `rag/pipeline.py` giảm từ 1.046 dòng xuống 418 dòng (giảm ~60%), giữ vai trò điều phối trung tâm giữa các module chuyên trách.

---

## 4. Modules mới và phân tách

| Module mới | Trách nhiệm chuyên biệt |
|---|---|
| `rag/pipeline_guards.py` | Kiểm tra an toàn đầu vào, phát hiện câu hỏi mơ hồ, chặn địa phương ngoài phạm vi hỗ trợ, chặn cấp cứu y tế và chủ đề ngoài thẩm quyền. |
| `rag/pipeline_cache.py` | Quản lý bộ nhớ đệm câu trả lời LRU Cache (`_PIPELINE_ANSWER_CACHE`), sinh cache key phân vùng theo session/domain. |
| `rag/pipeline_fast_path.py` | Xử lý Template Fast Path (<0.1s), trích xuất câu trả lời từ evidence, phát hiện câu trả lời rỗng/vô dụng. |
| `rag/pipeline_tools.py` | Điều phối gọi MCP tools đồng bộ an toàn qua thread pool, đóng gói metadata `tool_calls`. |
| `rag/streaming.py` | Quản lý tiến trình stream token, queue worker thread, phân tách giữa strict mode replay và friendly streaming. |
| `backend/services/background_tasks.py` | Bộ bọc `run_background_with_retry` giám sát background task, tự động retry lỗi mạng/DB transient, chống thất thoát task. |
| `backend/services/chat_service.py` | Xử lý toàn bộ logic nghiệp vụ hội thoại, xếp hàng semaphore, multi-intent và single-intent SSE streaming. |
| `benchmark/lib/` (`common.py`, `monitor.py`, `sse_client.py`, `stats.py`, `verdict.py`, `report.py`) | Khôi phục đầy đủ thư viện đo lường, giám sát RAM/CPU, client SSE và xuất báo cáo markdown/json cho benchmark. |

---

## 5. Background Task Reliability
- **Cơ chế hoạt động của `run_background_with_retry`:**
  1. Sử dụng `asyncio.create_task()` nhưng lưu strong reference vào `_ACTIVE_BACKGROUND_TASKS: set` để tránh việc Garbage Collector thu hồi task trước khi hoàn tất.
  2. Bắt các lỗi transient (mất kết nối DB, timeout kết nối, deadlock) và retry tối đa 3 lần với exponential backoff (`base_delay * 2^(attempt-1)`).
  3. Phân biệt rõ lỗi lập trình/dữ liệu không hợp lệ (`TypeError`, `ValueError`, `KeyError`, `AttributeError`) để **fail-fast ngay lập tức**, không retry lãng phí tài nguyên.
  4. Nếu thất bại sau tất cả các lần thử, ghi log đầy đủ stack trace bằng `logger.exception()`.
  5. Sự cố ở background task tuyệt đối không làm crash request chính hay làm gián đoạn luồng stream của người dùng.
- **Unit test kiểm chứng:**
  - File `tests/test_background_tasks.py` kiểm thử 4 trường hợp: Thành công lần đầu, Transient retry thành công ở lần 3, Hết lượt retry (exhausted), và Fail-fast với lỗi non-retryable. Kết quả: **4/4 PASS**.

---

## 6. Chính sách Exception Handling & Logging
- **Thay thế `except Exception: pass`:**
  - Tại `backend/main.py`: Bắt cụ thể `(urllib.error.URLError, TimeoutError, ConnectionRefusedError, json.JSONDecodeError, OSError)` khi thăm dò health check của model server.
  - Tại `backend/api/ingestion.py`: Thay các khối nuốt lỗi bằng ngoại lệ cụ thể `(FileNotFoundError, KeyError, ValueError, ImportError, AttributeError)` và ghi log debug.
  - Tại `backend/services/queue_service.py`: Ghi log debug khi multi-intent detection bị bỏ qua.
- **Top-level Transport & Worker Boundaries:**
  - Những nơi bắt buộc phải giữ broad exception handler (như vòng lặp WebSocket hay background worker) đều dùng `logger.exception(...)` để lưu giữ toàn bộ traceback phục vụ chẩn đoán, đồng thời gửi thông điệp thân thiện, an toàn ra ngoài client mà không làm lộ stack trace nội bộ.
- **Logging có ngữ cảnh:**
  - Chuyển đổi các lệnh `print` sản xuất sang `logging.getLogger(__name__)` với các mức `debug`, `info`, `warning`, `error`, `exception`.
  - Tuyệt đối không log thông tin nhạy cảm: token, cookie, mật khẩu, dữ liệu cá nhân thô (PII).

---

## 7. Chiến lược Dependency Locking
- **Chiến lược hai tầng (Two-Tier Dependency Management):**
  1. `requirements.in`: Khai báo các thư viện trực tiếp cấp cao của dự án kèm ngưỡng phiên bản tối thiểu tương thích.
  2. `requirements-lock.txt`: Khóa cứng chính xác 197 gói thư viện dựa trên môi trường Python 3.12.10 đã chạy kiểm thử thành công 100%.
- **Môi trường ghi nhận:** `Python 3.12.10` trên Windows 11 (tương thích Linux x86_64).
- **Hướng dẫn cài đặt tái lập:**
  ```bash
  python -m pip install -r requirements-lock.txt
  ```

---

## 8. Khôi phục Benchmark Reproducibility
- **Khắc phục root cause:**
  - Sửa `.gitignore`: Đổi `lib/` thành `/lib/` (anchored root) và bổ sung `!benchmark/lib/` cùng `!multi_domain_system/benchmark/lib/`.
  - Khôi phục module `benchmark/lib/` với 6 tệp helper chuẩn: `common.py`, `monitor.py`, `sse_client.py`, `stats.py`, `verdict.py`, `report.py`.
  - Đồng bộ các thư mục `cases/`, `suites/`, `selftest/`, `results/` vào thư mục gốc `benchmark/`.
  - Sửa `selftest/mock_server.py` trỏ đúng file golden set hiện có (`domains/cuisine_demo/golden_set.json`).
- **Lệnh thực thi từ project root:**
  ```bash
  # Tự kiểm tra với mock server
  python benchmark/selftest/mock_server.py --port 8765 --send-mode &
  python -m benchmark.run_benchmark --base-url http://127.0.0.1:8765 --watch-port 8765 --quick --no-fail-exit

  # Benchmark với server thật đang chạy trên cổng 8000
  python -m benchmark.run_benchmark --quick --no-fail-exit
  ```
- **Kết quả smoke test:** Suite `rules` chạy thành công qua mock server, ghi nhận số liệu và tự động sinh báo cáo tại `benchmark/results/`.

---

## 9. Bằng chứng kiểm thử (Test Evidence)

### A. Kiểm thử biên dịch (Compilation)
```powershell
python -m py_compile rag/pipeline.py rag/pipeline_guards.py rag/pipeline_cache.py rag/pipeline_fast_path.py rag/pipeline_tools.py rag/streaming.py backend/main.py backend/api/chat.py backend/api/socket.py backend/services/chat_service.py backend/services/background_tasks.py
```
-> **PASS (Exit code 0)**.

### B. Unit Test (Background Tasks)
```powershell
python -m pytest tests/test_background_tasks.py
```
-> **4 passed in 0.16s (PASS)**.

### C. Benchmark Smoke Test
```powershell
python -m benchmark.run_benchmark --base-url http://127.0.0.1:8765 --watch-port 8765 --suites rules --quick --no-fail-exit
```
-> **PASS (Exit code 0, tạo báo cáo hoàn chỉnh)**.

### D. Hệ thống Runtime & 5 Test Cases Layer 2
Khởi chạy thực tế: Backend port 8000, Llama-3B port 8090, Llama-1.5B port 8081.
- **GET `/health`**: `{"status": "ok"}` -> **PASS**.
- **GET `/api/system/status`**: `{"all_ready": true}` -> **PASS**.
- **Case 1 ("Tôi muốn làm thủ tục"):** Kích hoạt `needs_clarification=True`, hỏi lại tên thủ tục cụ thể -> **PASS**.
- **Case 2 ("Tôi muốn đăng ký kết hôn ở Hà Nội"):** Location Guard phát hiện ngoài phạm vi hỗ trợ TP.HCM -> **PASS**.
- **Case 3 ("Tôi muốn đăng ký kết hôn ở TP.HCM"):** Trả lời đúng thủ tục kết hôn `PROC_004` -> **PASS**.
- **Case 4 (Cùng session: "Lệ phí bao nhiêu?"):** Kế thừa chính xác context `PROC_004`, báo lệ phí đăng ký kết hôn -> **PASS**.
- **Case 5 (Cùng session: "Thời gian giải quyết bao lâu?"):** Kế thừa chính xác context `PROC_004`, báo thời gian giải quyết -> **PASS**.
- **WebSocket Streaming (`/ws/chat`):** Stream 140 token chunks trước event `done`, dữ liệu evidence và done đầy đủ -> **PASS**.
- **SSE Streaming (`/api/chat/stream`):** Stream 193 token chunks trước event `done`, dữ liệu UTF-8 đầy đủ -> **PASS**.
- **Unicode Integrity:** Không có bất kỳ lỗi vỡ ký tự mojibake nào (`Ã`, `Ä`, `á»`) -> **PASS**.

---

## 10. Giới hạn còn lại (Remaining Limitations)
1. **In-process Background Queue:** Cơ chế `run_background_with_retry` hiện chạy trên in-memory task loop của tiến trình Python. Nếu tiến trình server bị kill đột ngột (SIGKILL / mất nguồn máy chủ) đúng lúc task đang chờ delay để retry, tác vụ đó sẽ mất. Trong tương lai nếu yêu cầu độ bền dữ liệu tuyệt đối (Guaranteed Delivery), cần xem xét hàng đợi bền vững bên ngoài (như Redis / Celery / PG Queue).
2. **Mock Server Benchmark Dataset:** File `selftest/mock_server.py` hiện chỉ giả lập 2 domain (`administrative_procedures` và `cuisine_demo`). Nếu chạy benchmark đầy đủ các domain khác cần cấu hình thêm golden set tương ứng.
3. **Phụ thuộc CPU/GPU Local:** Tốc độ streaming token vẫn phụ thuộc vào tải cục bộ của máy tính chạy llama-server.
