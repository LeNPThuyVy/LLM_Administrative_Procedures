# B3 – Threshold Calibration

## Kết quả thực nghiệm

- Dataset: Administrative Procedures
- Embedding: BGE-M3
- Vector database: Qdrant
- Golden set: 30 câu
- Out-of-scope test: 10 câu

| Chỉ số               | Kết quả |
| -------------------- | ------- |
| Retrieval@1          | 90.0%   |
| Retrieval@5          | 93.3%   |
| MRR                  | 0.9111  |
| OOD score thấp nhất  | 0.3346  |
| OOD score cao nhất   | 0.7245  |
| OOD score trung bình | 0.4952  |
| OOD vượt ngưỡng 0.50 | 5/10    |

## Nhận xét

Ngưỡng 0.50 chưa đủ để loại bỏ toàn bộ câu hỏi ngoài phạm vi. Một số câu không liên quan vẫn đạt điểm retrieval tương đối cao.

Dữ liệu có thủ tục đăng ký hộ kinh doanh. Vì vậy lỗi trả nhầm sang đăng ký kết hôn cần được xử lý ở retrieval/ranking, không thể coi là thiếu dữ liệu.

## Hướng xử lý

- Tạm giữ threshold hiện tại ở 0.50.
- Kết hợp kiểm tra phạm vi domain và xác minh evidence.
- Chưa tăng threshold khi chưa đánh giá ảnh hưởng đến câu hỏi hợp lệ.
- Bổ sung kiểm thử end-to-end strict/friendly trước khi merge.

**Trạng thái:** Đã hoàn thành đo đạc ban đầu. Chưa chốt ngưỡng tối ưu.
