# Benchmark Performance & Accuracy (After Speedup & Multi-turn Fixes)

> Thời điểm đo: 12/10/2026
> Bộ kịch bản: `task/scenarios_admin.json` (27 turns)
> Chế độ: FAST MODE (MOCK LLM GENERATOR)

## 1. Kết quả Độ chính xác (Accuracy)

- **Tổng số ca kiểm thử**: 27
- **Số ca đạt (Pass)**: 27 (100.0%)
- **Số ca thất bại (Fail)**: 0 (0.0%)

## 2. Kết quả Độ trễ (Latency)

| Chỉ số | Thời gian (FAST MODE (MOCK LLM GENERATOR)) |
|---|---|
| **Trung bình (Avg)** | 3.37s |
| **p50 (Median)** | 1.22s |
| **p90** | 10.24s |
| **p95** | 10.33s |

---
*Ghi chú: Benchmark đánh giá toàn diện pipeline sau tối ưu BGE-M3 LRU Cache, Two-step Soft Boost, Fast Path và Alias Matching.*
