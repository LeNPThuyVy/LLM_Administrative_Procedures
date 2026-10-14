# Benchmark Performance & Accuracy (After Speedup & Multi-turn Fixes)

> Thời điểm đo: 12/10/2026
> Bộ kịch bản: `task/scenarios_admin.json` (27 turns)
> Chế độ: FAST MODE (MOCK LLM GENERATOR)

## 1. Kết quả Độ chính xác (Accuracy)

- **Tổng số ca kiểm thử**: 27
- **Số ca đạt (Pass)**: 26 (96.3%)
- **Số ca thất bại (Fail)**: 1 (3.7%)

## 2. Kết quả Độ trễ (Latency)

| Chỉ số | Thời gian (FAST MODE (MOCK LLM GENERATOR)) |
|---|---|
| **Trung bình (Avg)** | 2.42s |
| **p50 (Median)** | 0.73s |
| **p90** | 5.34s |
| **p95** | 5.41s |

---
*Ghi chú: Benchmark đánh giá toàn diện pipeline sau tối ưu BGE-M3 LRU Cache, Two-step Soft Boost, Fast Path và Alias Matching.*
