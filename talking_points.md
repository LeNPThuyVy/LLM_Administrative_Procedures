# Talking Points - Quốc An

## Phần em phụ trách

Em phụ trách Backend/API và cơ chế Queue của hệ thống.

## Ngày 1

- Xây dựng FastAPI skeleton.
- Tạo POST /api/chat.
- Trả dữ liệu bằng SSE.
- Phân loại request simple, multi-step, tool.
- Xây dựng session lock.
- Xây dựng giới hạn concurrency bằng Semaphore.

## Ngày 2

- Kết nối Backend với Context Service thật.
- Kết nối Backend với AI Core/RAG thật.
- Hoàn thiện POST /api/sessions.
- Hoàn thiện GET /api/sessions/{id}/messages.
- Lưu lịch sử hội thoại vào PostgreSQL.
- Kiểm tra Evidence, Chunk, Done và Citation.

## Ngày 3

- Test nhiều session đồng thời.
- Test cùng một session xử lý tuần tự.
- Kiểm tra Queue và Semaphore.
- Phát hiện lỗi thiếu RAM khi chạy nhiều RAG song song.
- Tách Queue test khỏi RAG để kiểm tra đúng phần Backend.
- Tổng hợp bug và chuẩn bị nội dung demo.

## Luồng hoạt động

Client gửi câu hỏi
→ FastAPI nhận request
→ Queue kiểm tra session
→ Context Service lấy context
→ RAG xử lý câu hỏi
→ Backend trả Evidence và Chunk bằng SSE
→ Trả Done
→ update_memory chạy nền
→ Lưu lịch sử vào PostgreSQL.

## Kết quả

- Backend kết nối được với Context Service.
- Backend kết nối được với RAG.
- Lưu và đọc lại hội thoại từ PostgreSQL thành công.
- Session lock hoạt động đúng.
- Queue xử lý tuần tự trong cùng session.
- Semaphore giới hạn được số request chạy đồng thời.

## Vấn đề hiện tại

Khi chạy nhiều request RAG thật cùng lúc trên máy RAM thấp,
model có thể gây MemoryError.

Đây là vấn đề tài nguyên của phần AI model,
không phải lỗi logic của Queue.