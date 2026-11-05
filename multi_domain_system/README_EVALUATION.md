# BÁO CÁO KIỂM THỬ VÀ ĐÁNH GIÁ HỆ THỐNG

**Dự án:** LLM_Administrative_Procedures — Trợ lý AI thủ tục hành chính  
**Phiên bản được kiểm thử:** `main`, commit `034b965` (ngày 22/10/2026)  
**Môi trường:** Windows, Python 3.12, FastAPI `http://127.0.0.1:8002`, BGE-M3, Qdrant Cloud, PostgreSQL, Qwen2.5 3B và 1.5B (GGUF), llama-server.  
**Kiểu kiểm thử:** black-box qua giao diện / HTTP API; retrieval golden set 100 trường hợp; benchmark 5 request thủ công và 12 request mở rộng; quan sát RAM theo tiến trình.  
**Trạng thái tài liệu:** Báo cáo kết quả **đã quan sát**; những mục chưa có dữ liệu được ghi nhận riêng, không suy ra PASS.

## 1. Mục tiêu và phạm vi

Đánh giá (1) khả năng hệ thống khởi động và đáp ứng request; (2) thời gian thực thi API; (3) RAM tiêu thụ; (4) truy xuất đúng tài liệu; (5) nội dung, dẫn chứng và xử lý câu hỏi ngoài phạm vi. Các số liệu đo trên máy chạy demo, không phải số đo triển khai production.

## 2. Trạng thái khởi động

- `GET /health`: phản hồi `status=ok`.
- `GET /api/system/status`: `status=ready`, `all_ready=true`; `db=true`, `embedding=true`, `vector_store=true`, `llm_3b=true`, `llm_1_5b=true`.
- Đã mở giao diện và gửi câu hỏi thủ tục hành chính khi chế độ Mock API tắt.
- Chỉ báo sẵn sàng **không tự thân chứng minh** mọi chức năng hoặc từng lần suy luận thành công; đã bổ sung kiểm tra `event: done` trên API.

## 3. Thời gian thực thi (HTTP/SSE end-to-end)

Chạy 5 request **tuần tự**, mỗi request dùng `session_id` khác nhau, `POST /api/chat`, kiểm tra HTTP 200 và sự kiện `done`. Dùng PowerShell `Stopwatch`; thời gian gồm truyền nhận và toàn bộ quá trình trả response SSE; **chưa** đo TTFT.

| STT | Câu hỏi | Thời gian (giây) | HTTP | SSE done |
|---:|---|---:|---:|---|
| 1 | Đăng ký khai sinh cần hồ sơ gì? | 7,63 | 200 | Có |
| 2 | Đăng ký kết hôn cần giấy tờ gì? | 3,78 | 200 | Có |
| 3 | Lệ phí đăng ký khai sinh bao nhiêu? | 2,45 | 200 | Có |
| 4 | Đăng ký hộ kinh doanh mất bao lâu? | 14,56 | 200 | Có |
| 5 | Xin cấp số nhà cần những gì? | 11,98 | 200 | Có |

**Chỉ số:** trung bình **8,08 giây**; trung vị p50 **7,63 giây**; tối thiểu **2,45 giây**; tối đa **14,56 giây**; p95 **14,04 giây** (phân vị nội suy tuyến tính); tỷ lệ HTTP 200 và `done` là **5/5**. Cỡ mẫu chỉ có 5 nên p95 là **tham khảo**, chưa thể suy rộng cho tải nhiều người hoặc traffic thực tế.

Một request độc lập khác (hỏi đăng ký kết hôn TP.HCM cần giấy tờ gì) mất **3,91 giây**, HTTP 200, có `event: evidence` và `event: done` (không tính gộp vào mẫu 5 request trên). Lần thử 1,35 giây trước đó **không hợp lệ** vì request bị PowerShell chặn với cảnh báo `-UseBasicParsing`.

## 4. Đánh giá độ chính xác retrieval

Bộ `domains/administrative_procedures/golden_set.json`: **100 ca**, trong đó 95 ca in-scope, 5 ca out-of-scope. Thực thi:

```powershell
.\.venv\Scripts\python.exe scripts/eval_golden_set.py --domain administrative_procedures --top-k 5
```

| Chỉ số | Đã đo | Cách hiểu |
|---|---:|---|
| Retrieval@1 | **83/95 = 87,4%** | Đúng tài liệu đứng vị trí đầu |
| Retrieval@3 | **88/95 = 92,6%** | Có tài liệu đúng trong top 3 |
| Retrieval@5 | **92/95 = 96,8%** | Có tài liệu đúng trong top 5 |
| MRR | **0,9042** | Trung bình nghịch đảo thứ hạng tài liệu đúng |
| Field Match | **65/95 = 68,4%** | Trường thông tin trả về đầu tiên khớp kỳ vọng |
| Out-of-scope rejection | **1/5 = 20,0%** | Truy xuất từ chối đúng ca ngoài tập dữ liệu |

**Các ca không tìm thấy đúng tài liệu trong top 5:** `GS_086`, `GS_087`, `GS_088`. **Các ca ngoài phạm vi bị false positive:** `GS_096`, `GS_097`, `GS_098`, `GS_100`. `GS_099` được từ chối đúng.

**Hạn chế:** đây là đánh giá **retrieval**, không phải tỷ lệ trả lời đúng hoặc độ chính xác pháp lý cuối cùng; điểm retrieval có cộng các tín hiệu trọng số nội bộ nên không diễn giải trực tiếp là xác suất đúng. Độ chính xác nguồn/luật cần đối chiếu với thủ tục và văn bản chính thức còn hiệu lực.

**File kết quả gốc được tạo trên máy kiểm thử:** `docs/eval_golden_set_administrative_procedures_20261022.json` (không đính kèm trong gói này; cần chép vào khi bàn giao). File latency gốc: `docs/benchmark_latency_20261022.csv` (không đính kèm trong gói này).

## 5. RAM và tài nguyên

Đo một lần bằng PowerShell `Get-Process ... WorkingSet64`:

| Tiến trình | PID | Working Set (MB) |
|---|---:|---:|
| llama-server | 2340 | 1.996,63 |
| llama-server | 23140 | 1.116,13 |
| python | 11768 | 55,86 |
| python | 23652 | 4,19 |
| python | 25800 | 2.065,16 |
| **Tổng số học** | | **5.237,97** |

**Cảnh báo phương pháp:** tổng Working Set trên đây có thể **đếm trùng các trang bộ nhớ chia sẻ** giữa tiến trình, và các tiến trình Python chưa được ánh xạ đầy đủ theo vai trò. Đây là ảnh chụp tức thời; xem **Mục 6.1** để biết thêm các đỉnh quan sát theo PID khi chạy 12 ca mở rộng.

## 6. Kiểm thử mở rộng trên API thật (22/10/2026, 13:12:53)

**Nguồn:** `extended_evaluation/summary.json` và `extended_evaluation/SUMMARY.md`, được sinh từ script trên API `http://127.0.0.1:8002`, không phải mock. 12 ca gồm nghiệp vụ phổ biến, chào hỏi, câu ngoài phạm vi, ngoài địa bàn và prompt injection.

| Chỉ số | Kết quả | Diễn giải |
|---|---:|---|
| Request có HTTP 200 + SSE `done` | **12/12 (100%)** | Hoàn thành kỹ thuật, **không đồng nghĩa câu trả lời đúng** |
| Request lỗi | **0/12** | Trong đợt kiểm thử này |
| Thời gian trung bình | **3,281 giây** | End-to-end HTTP/SSE |
| p50 thời gian | **1,928 giây** | Trung vị theo script |
| p95 thời gian | **8,500 giây** | Mẫu nhỏ, mang tính tham khảo |
| p50 nhận nội dung SSE đầu tiên | **1,800 giây** | Chưa chắc là TTFT token sinh bởi LLM |
| p95 nhận nội dung SSE đầu tiên | **4,648 giây** | Chưa chắc là TTFT token sinh bởi LLM |
| Ca có mệnh đề `unsupported` vẫn xuất hiện | **2/12** | Một dấu hiệu lỗi kiểm soát đầu ra, không khẳng định mệnh đề sai luật |
| Ca đúng tài liệu theo kỳ vọng | **7/7 ca được chấm** | Chỉ đánh giá `document_id` ở các ca có nhãn; **không phải accuracy pháp lý** |

**Hai ca có `unsupported_leaks=1` theo log chạy mở rộng:** *Khai sinh – hồ sơ* (7,839 giây), *Kết hôn – hồ sơ* (2,477 giây). Cần xem `api_cases.csv` trên máy kiểm thử để đối chiếu claim, nội dung câu trả lời và evidence. Dữ liệu chi tiết CSV **chưa được đính kèm trong bản bàn giao này**; không được suy diễn tất cả ca ngoài phạm vi/injection đã PASS chỉ từ trạng thái HTTP 200 và `done`.

### 6.1. RAM đỉnh quan sát trong đợt mở rộng

Script ghi **giá trị Working Set cao nhất được quan sát cho từng PID**; đây không phải tổng RAM riêng tư của dịch vụ và không bảo đảm các đỉnh xảy ra cùng một thời điểm.

| Process | PID | RAM lớn nhất quan sát (MB) |
|---|---:|---:|
| llama-server.exe | 2340 | 2.111,77 |
| llama-server.exe | 23140 | 1.136,70 |
| python.exe | 25800 | 2.050,66 |
| python.exe | 11768 | 54,93 |
| python.exe | 25440 | 28,39 |
| python.exe | 23652 | 4,14 |
| python.exe | 25844 | 4,11 |

Tổng số học các giá trị đỉnh riêng lẻ = **5.390,70 MB**, **KHÔNG phải RAM đỉnh đồng thời**: có thể tính trùng memory chia sẻ, gồm Python ngoài ứng dụng, và các đỉnh khác thời điểm. Muốn xác định RAM đỉnh đồng thời theo nhóm process, cần dùng `ram_samples.csv`, nhận diện PID thuộc hệ thống và cộng theo từng timestamp, sau đó lấy giá trị lớn nhất.

### 6.2. Nhận xét chất lượng đáp án

Bộ đánh giá nội bộ báo 7/7 ca có `expected_document_id` tìm trúng tài liệu, nhưng **không có kiểm định chuyên gia đối với tính hợp pháp, tính đầy đủ và tính cập nhật của câu trả lời**. Đáng chú ý 2/12 ca vẫn chứa nội dung bị đánh dấu `unsupported`. Quy tắc đánh dấu nội bộ có thể false positive, nên cần so sánh bằng chứng trước khi sửa/xóa nội dung.

**Một ca API đã kiểm tra riêng trước đó:** “Đăng ký kết hôn tại TP.HCM cần giấy tờ gì?” (3,91 giây, `strict`, `PROC_004`) có mệnh đề được verifier đánh dấu `unsupported` với lý do xung đột phủ định nhưng vẫn nằm trong `done.answer`. Citation trỏ tới tên miền nguồn chung, chưa trỏ chính xác văn bản pháp lý. Kết quả này độc lập với 12 ca mở rộng, không cộng vào mẫu thống kê.

## 7. Rủi ro và ưu tiên khắc phục

| Ưu tiên | Vấn đề | Khuyến nghị | Trạng thái |
|---|---|---|---|
| **Cao** | Out-of-scope rejection tại retrieval chỉ **1/5** | Điều chỉnh scope gate, kiểm tra kỹ ngưỡng và mở rộng tập âm tính | Chưa đạt theo mẫu hiện tại |
| **Cao** | **2/12** ca có `unsupported` vẫn xuất hiện trong câu trả lời | Đối chiếu bằng chứng, sửa khâu lọc đầu ra, bổ sung regression tests | Cần sửa/đánh giá lại |
| **Cao** | Trích dẫn thiếu URL trang thủ tục/văn bản cụ thể | Lưu URL, version và ngày hiệu lực của nguồn | Cần hoàn thiện |
| **Trung bình** | Field Match **65/95 = 68,4%** | Tối ưu tìm/rerank đúng `docs`, `fee`, `time`, `method` | Cần cải thiện |
| **Trung bình** | 5 + 12 request, p95 chưa đại diện tải thực tế | Chạy load test, phân biệt cold/warm và đo TTFT token | Chưa đánh giá đầy đủ |
| **Trung bình** | RAM theo tên process, có process không liên quan | Dùng chuỗi `ram_samples.csv`, lọc PID và thời điểm | Chưa có RAM peak hệ thống chuẩn |
| **Trung bình** | Chưa có đánh giá chuyên gia cho an toàn và đúng luật | Audit thủ công từng câu, kiểm thử đa lượt/injection đầy đủ | Chưa hoàn tất |
| **Trung bình** | `benchmark/run_benchmark.py` phụ thuộc `benchmark.lib` nhưng bản `main` đã kiểm tra không có thư mục này | Đồng bộ module thiếu hoặc sửa bộ benchmark chính | Chưa khắc phục |

## 8. Dữ liệu bàn giao và cách tái lập

**File trong gói này:**

- `README_EVALUATION.md`: toàn bộ báo cáo này.
- `extended_evaluation/summary.json`, `extended_evaluation/SUMMARY.md`: kết quả tổng hợp **12 ca thực tế** do người kiểm thử cung cấp.
- `run_extended_evaluation.py`: script chạy API và đo RAM.
- `CHAY_NGAY.txt`: hướng dẫn ngắn.

**Các file vẫn còn trên máy kiểm thử và cần đính kèm khi nộp đủ bằng chứng:**

- `docs/eval_golden_set_administrative_procedures_20261022.json` – chi tiết 100 ca golden set.
- `docs/benchmark_latency_20261022.csv` – 5 thời gian đo thủ công.
- `docs/extended_evaluation_20261022/api_cases.csv` – câu hỏi, kết quả, claim `unsupported`.
- `docs/extended_evaluation_20261022/ram_samples.csv` – mẫu RAM theo thời gian.

Có thể chạy lại mở rộng từ thư mục gốc dự án bằng PowerShell (cần server thật đã bật):

```powershell
.\.venv\Scripts\python.exe .\run_extended_evaluation.py --url http://127.0.0.1:8002 --out-dir .\docs\extended_evaluation_20261022
```

Các request API ghi lịch sử chat theo thiết kế; chỉ nên chạy trên môi trường kiểm thử được phép. Không nạp lại ingestion hoặc sửa vector database khi chưa có yêu cầu riêng.

## 9. Kết luận bàn giao

Đã **thực thi đánh giá thực nghiệm** trên bản `main` commit `034b965`: ứng dụng khởi chạy, các dịch vụ báo sẵn sàng, golden set 100 ca, 5 request độ trễ cơ bản và **12 request mở rộng đều hoàn tất HTTP/SSE**. Retrieval@5 **96,8%** trên 95 ca hợp lệ; 12 ca mở rộng có thời gian trung bình **3,281 giây** và p95 **8,500 giây**. Đã có bảng RAM đỉnh **theo PID**.

**Chưa đủ căn cứ nghiệm thu hệ thống hoàn toàn:** tỷ lệ từ chối ngoài phạm vi ở tầng Retrieval **20%**, tồn tại **2/12** ca xuất hiện mệnh đề bị đánh dấu `unsupported` trong đầu ra, và chưa có kiểm chứng pháp lý độc lập / load test quy mô đủ. Kết quả `7/7` đúng document ID không được báo thành 100% accuracy câu trả lời. Đề nghị chuyển nhóm sửa lỗi cao trước, sau đó chạy lại regression tests và đính kèm toàn bộ CSV/JSON chi tiết.
