# Benchmark hệ thống Universal Domain AI Assistant

Đo hệ thống **từ bên ngoài qua HTTP** (`POST /api/chat`, SSE) giống hệt người dùng thật, kèm giám sát RAM/CPU/GPU của process server. Vì chỉ dựa vào giao thức, bộ này dùng được cho **mọi domain** (hành chính, du lịch, ẩm thực…) mà không phải sửa code.

## Cài đặt & chạy

```bash
pip install psutil pyyaml          # httpx không cần
# Cách 1: server đã chạy sẵn (khuyên dùng PYTHONUNBUFFERED=1 và ghi log ra file để có bảng "thời gian từng bước")
PYTHONUNBUFFERED=1 python backend/main.py > server.log 2>&1
python -m benchmark.run_benchmark --quick --server-log server.log

# Cách 2: để benchmark tự bật server + đo RAM lúc khởi động nguội
python -m benchmark.run_benchmark --launch "python -m uvicorn backend.main:app --port 8000" --full --tag truoc_toi_uu

# So sánh trước/sau khi tối ưu
python -m benchmark.run_benchmark --full --tag sau_toi_uu --compare benchmark/results/bench_truoc_toi_uu.json
```

Chạy từ **thư mục gốc dự án**. Kết quả: `benchmark/results/bench_<tag>.md` (đọc) và `.json` (so sánh). Exit code 1 nếu có chỉ số trượt (dùng được cho CI; thêm `--no-fail-exit` để tắt).

| Tuỳ chọn | Ý nghĩa |
|---|---|
| `--quick` | bộ nhỏ, ~5–10 phút |
| `--full` | thêm soak test (mặc định 10 phút, chỉnh trong config) |
| `--suites quality,rules,latency,load,soak` | chọn suite |
| `--pid N` / `--watch-port P` | chỉ định process cần đo RAM (mặc định nhận theo cổng 8000, 8080) |
| `--launch "cmd"` | tự khởi động server, đo thời gian khởi động và RAM sau warm-up |

## Các suite và ý nghĩa

| Suite | Đo gì | Trả lời câu hỏi |
|---|---|---|
| `quality` | Đúng tài liệu (qua citation), độ phủ từ khoá, hành vi trả lời/hỏi lại/từ chối, hội thoại nhiều lượt | Trả lời có đúng và có nguồn không? |
| `rules` | Domain **strict**: disclaimer, không bịa, chặn injection/ngoài phạm vi/PII. Domain **friendly**: giọng thân thiện, không nặng nề. Input lạ không gây 5xx | Có tuân thủ luật chơi theo từng domain không? (yêu cầu 3) |
| `latency` | TTFT, tổng thời gian p50/p90/p95/p99, tốc độ sinh, hiệu quả cache, request đầu tiên | 1 người dùng chờ bao lâu? |
| `load` | Thang 1→16 người dùng đồng thời: lỗi, timeout, p95, req/s, **RAM đỉnh mỗi mức**; phát hiện treo và khả năng hồi phục; 3 request cùng session | Có sập / treo khi đông người không? (yêu cầu 2) |
| `soak` | Chạy tải ổn định lâu: **độ dốc RAM (MB/phút)** từng process, độ trôi p95, tỉ lệ lỗi | Có rò rỉ RAM / chậm dần không? |
| tài nguyên | RSS API + llama-server (tách riêng), CPU, thread, GPU (nếu có `nvidia-smi`), RAM trống của máy – theo từng giai đoạn | Cần máy bao nhiêu RAM để deploy? |

**Đọc RAM:** RSS là bộ nhớ vật lý thật sự đang giữ. Model GGUF được mmap nên RSS của llama-server có thể tăng dần ở các request đầu rồi ổn định – vì vậy soak bỏ 20% đầu khi tính độ dốc. CPU% là tổng trên mọi lõi nên có thể > 100%. GPU là mức dùng toàn máy, không tách theo process.

## Thêm domain mới (vd ẩm thực)

1. Tạo `domains/am_thuc/` + `golden_set.json` theo format cũ (`question`, `expected_document_id`, `expected_field`, `expected_keywords`).
2. Thêm 1 mục vào `datasets:` trong `config.yaml`.
3. (Tuỳ chọn) thêm vài ca vào `cases/rules_cases.json` cho luật riêng của domain.

## Ngưỡng (SLO)

Toàn bộ nằm ở mục `slo:` trong `config.yaml`. Đây là **giá trị khởi đầu**, hãy chốt lại với mentor theo phần cứng deploy thật (ví dụ ngưỡng RAM mặc định 12 GB chỉ là ước lượng).

## Giới hạn cần biết

- `doc_hit` suy ra từ `document_id` trong evidence/citation trả về; câu trả lời đúng nhưng thiếu citation tính là trượt.
- Kiểm tra "nâng strict khi gặp visa/thuốc" cần server trả `mode` trong event `done`. Hiện `chat.py` chưa gửi nên check này được **bỏ qua (SKIP)**, không tính trượt. Thêm `"mode": result.get("mode")` vào `done_data` là thay đổi cộng thêm, không phá UI.
- Kiểm tra giọng điệu `friendly` chỉ là heuristic từ khoá; nên bổ sung chấm tay ~20 câu.
- Cache hiện có khoá theo `session_id`, nên bảng "Tác động của cache" chỉ phản ánh cache trong cùng một session.
- Thang đồng thời chạy trên **một máy** (client + server chung tài nguyên) nên số liệu hơi bi quan; khi deploy thật hãy chạy client từ máy khác.

## Tự kiểm tra bộ benchmark (không cần model)

```bash
python benchmark/selftest/mock_server.py --port 8765 --send-mode &
python -m benchmark.run_benchmark --base-url http://127.0.0.1:8765 --watch-port 8765 --quick
# thử các lỗi cố ý:  --buggy-semaphore (treo khi đồng thời)   --leak-mb 2 (rò RAM)
```
