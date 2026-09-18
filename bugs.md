# Bugs phát hiện - Ngày 3

## 1. RAG trả sai thủ tục

- Input:
  "Tôi cần đăng ký hộ kinh doanh"

- Kết quả thực tế:
  Hệ thống trả về "Thủ tục đăng ký kết hôn".

- Nhận xét:
  Backend, SSE và Memory vẫn hoạt động.
  Lỗi có khả năng nằm ở Retrieval/Rerank của RAG.

- Trạng thái:
  Đã ghi nhận.


## 2. Citation không serialize được

- Lỗi:
  Object of type Citation is not JSON serializable

- Nguyên nhân:
  Citation là object lồng trong kết quả AI.

- Cách xử lý:
  Dùng jsonable_encoder trước khi trả dữ liệu SSE.

- Trạng thái:
  Đã sửa.


## 3. ChromaDB chưa có collection procedures

- Lỗi:
  Collection [procedures] does not exist.

- Cách xử lý:
  Chạy scripts/build_index.py để tạo index từ procedures.json.

- Trạng thái:
  Đã sửa.


## 4. PostgreSQL chưa chạy

- Hiện tượng:
  POST /api/sessions trả lỗi 500.

- Lỗi:
  ConnectionRefusedError

- Nguyên nhân:
  PostgreSQL service chưa được bật.

- Cách xử lý:
  Khởi động service postgresql-x64-18.

- Trạng thái:
  Đã sửa.


## 5. Hết RAM khi test nhiều request RAG

- Hiện tượng:
  Gửi nhiều request /api/chat đồng thời.

- Lỗi:
  MemoryError
  memory allocation failed

- Nguyên nhân:
  Nhiều pipeline RAG cùng load model lớn trên máy RAM khoảng 8 GB.

- Hậu quả:
  SSE bị ngắt giữa chừng.
  Client nhận RemoteProtocolError / ReadError.

- Hướng xử lý:
  Giảm concurrency.
  Tái sử dụng model đã load.
  Dùng model nhẹ hơn hoặc máy nhiều RAM hơn.

- Trạng thái:
  Đã phát hiện qua load test Ngày 3.