# Demo Questions — bộ câu hỏi mẫu dùng chung cho cả nhóm

> Dùng để test xuyên suốt Ngày 1 và Ngày 2. Không tự ý đổi câu hỏi giữa chừng —
> nếu cần đổi, báo cả nhóm trước (đúng nguyên tắc trong TASK_2_NGAY_DEMO.md).
> Người 2 cần đảm bảo `data/procedures.json` có đủ dữ liệu để trả lời được 5 câu này.

## Bộ câu hỏi chính thức

| # | Câu hỏi | Câu trả lời kỳ vọng (ngắn gọn) | Kết quả (Ngày 1) | Kết quả (Ngày 2) |
|---|---|---|---|---|
| 1 | Tôi muốn đăng ký hộ kinh doanh ở Bình Dương cần giấy tờ gì? | Liệt kê giấy tờ cần thiết (giấy đề nghị, CCCD, hợp đồng thuê địa điểm...) kèm evidence trích dẫn văn bản pháp luật | ☐ Pass / ☐ Fail | ☐ Pass / ☐ Fail |
| 2 | Thủ tục làm căn cước công dân lần đầu cần chuẩn bị gì? | Liệt kê hồ sơ, nơi nộp, thời gian xử lý | ☐ Pass / ☐ Fail | ☐ Pass / ☐ Fail |
| 3 | Đăng ký tạm trú cho người thuê nhà cần những bước nào? | Các bước đăng ký tạm trú, thời hạn, cơ quan tiếp nhận | ☐ Pass / ☐ Fail | ☐ Pass / ☐ Fail |
| 4 | Tôi mới chuyển hộ khẩu, cần làm lại giấy tờ gì cho con đi học? | Hướng dẫn thủ tục chuyển trường / xác nhận cư trú liên quan | ☐ Pass / ☐ Fail | ☐ Pass / ☐ Fail |
| 5 | Xin cấp lại CCCD bị mất thì làm ở đâu, mất bao lâu? | Nơi nộp hồ sơ, thời gian xử lý, lệ phí (nếu có) | ☐ Pass / ☐ Fail | ☐ Pass / ☐ Fail |

## Câu hỏi "phá" (bổ sung Ngày 2 — test clarification / unsupported claim)

| # | Câu hỏi | Mục đích test | Kết quả |
|---|---|---|---|
| 6 | giấy tờ | Câu quá ngắn/mơ hồ → phải trigger `needs_clarification = true` | ☐ Pass / ☐ Fail |
| 7 | Thủ tục ly hôn ở nước ngoài cần những gì? | Ngoài phạm vi dữ liệu (chỉ có 15-20 thủ tục hành chính) → phải trả lời "không tìm thấy thông tin", không bịa | ☐ Pass / ☐ Fail |
| 8 | Tôi cần đăng ký hộ kinh doanh, à mà thôi, cho tôi hỏi về CCCD trước | Test multi-turn: đổi chủ đề giữa hội thoại | ☐ Pass / ☐ Fail |
| 9 | Tôi ở Bình Dương (câu 1) → "vậy còn lệ phí thì sao?" (câu 2) | Test structured_context giữ được `location` qua nhiều lượt, không cần lặp lại | ☐ Pass / ☐ Fail |
| 10 | (câu hỏi ngẫu nhiên không liên quan luật, vd: "hôm nay thời tiết thế nào") | Test hệ thống từ chối lịch sự, không cố trả lời sai phạm vi | ☐ Pass / ☐ Fail |

## Ghi chú khi test

- Test trực tiếp trên **HF Space đã deploy**, không test local (theo yêu cầu Ngày 1).
- Mỗi lần fail, ghi ngay vào `bugs.md` kèm câu hỏi, kết quả thực tế, và ảnh chụp màn hình nếu có.
- Ngày 1 chỉ cần ≥3/5 câu (1-5) đạt — chưa cần chạy bộ câu hỏi "phá".
