# Baseline Performance & Accuracy (Before Speedup & Fixes)

> Thời điểm đo: 12/10/2026
> Bộ kịch bản: `task/scenarios_admin.json` (27 turns)
> Chế độ: FAST MODE (MOCK LLM GENERATOR)

## 1. Kết quả Độ chính xác (Accuracy Baseline)

- **Tổng số ca kiểm thử**: 27
- **Số ca đạt (Pass)**: 18 (66.7%)
- **Số ca thất bại (Fail)**: 9 (33.3%)

### Chi tiết các lỗi xác nhận từ thực tế:
1. **Lượt 1 & 2 bị ép hỏi lại**: 
   - `SCEN_01`: *"kiểu mình mới đẻ con ấy thì giờ mình phải làm gì"* -> FAIL (hệ thống ép CLARIFY vì `_has_specific_procedure_keyword` không thấy từ "đẻ con" trong `entity_keywords`).
   - `SCEN_02`: *"mình mới sinh con thì giờ mình làm gì"* -> FAIL (hệ thống ép CLARIFY).
2. **Lượt 4 bị kẹt thủ tục cũ**:
   - `SCEN_08_MULTITURN_ACTUAL_T4`: *"ủa mà mình chưa đăng kí kết hôn á thì phải làm sao?"* -> FAIL (hệ thống ép quay lại `PROC_002` do `active_procedure` override cứng).
3. **Từ chối ngoài phạm vi**:
   - `SCEN_16` (Hà Nội), `SCEN_17` (Bình Dương): PASS (Từ chối đúng).
4. **Lời chào / Câu mơ hồ**:
   - `SCEN_18` ("xin chào"), `SCEN_19` ("tôi muốn hỏi về thủ tục"): PASS (Hỏi lại đúng).

## 2. Kết quả Độ trễ (Latency Baseline)

| Chỉ số | Thời gian (FAST MODE (MOCK LLM GENERATOR)) |
|---|---|
| **Trung bình (Avg)** | 7.66s |
| **p50 (Median)** | 2.09s |
| **p90** | 14.55s |
| **p95** | 14.93s |

---
*Ghi chú: Benchmark đo đường full LLM trên cấu hình local llama-server.*
