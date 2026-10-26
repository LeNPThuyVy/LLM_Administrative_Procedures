# Extended API evaluation

Các số liệu sau được đo **thật** từ API đang chạy; không khẳng định chính xác pháp lý.

```json
{
  "source": "fresh real API execution",
  "endpoint": "http://127.0.0.1:8002",
  "time": "2026-10-22 13:12:53",
  "cases": 12,
  "http200_done": 12,
  "error_count": 0,
  "latency_mean_s": 3.281,
  "latency_p50_s": 1.928,
  "latency_p95_s": 8.5,
  "first_content_p50_s": 1.8,
  "first_content_p95_s": 4.648,
  "first_content_note": "first SSE response content; not guaranteed actual token TTFT",
  "unsupported_leak_cases": 2,
  "expected_doc_hit_over_scored_cases": 7,
  "scored_cases": 7,
  "ram_peak_observed_mb_by_process": {
    "llama-server.exe:2340": 2111.77,
    "python.exe:11768": 54.93,
    "llama-server.exe:23140": 1136.7,
    "python.exe:23652": 4.14,
    "python.exe:25440": 28.39,
    "python.exe:25800": 2050.66,
    "python.exe:25844": 4.11
  },
  "ram_note": "Observed per-process RSS by process names, possible shared page double count and unrelated Python processes; not exact service memory/unique RAM",
  "scope_note": "Not a legal correctness assessment, out-of-scope requires human review"
}
```

Đọc `api_cases.csv` để xem câu hỏi lỗi và claim unsupported. `ram_samples.csv` để xem chuỗi mẫu RAM.
