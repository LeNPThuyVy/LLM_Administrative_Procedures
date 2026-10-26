# Trợ lý AI Thủ tục Hành chính Công TP.HCM (Standalone Project)

Dự án chuyên biệt hỗ trợ tra cứu thủ tục hành chính công một cửa tại TP. Hồ Chí Minh.
Dự án được tách độc lập hoàn toàn với hệ thống đa domain.

## Cấu trúc Dự án
- `backend/`: API Gateway (FastAPI + Uvicorn) phục vụ tại cổng **8003**.
- `rag/`: Lõi RAG pipeline (BGE-M3 retrieval + Qwen2.5 local inference + trích dẫn nghiêm ngặt).
- `data/`: Dữ liệu thủ tục hành chính `procedures.json`.
- `domains/administrative_procedures/`: Cấu hình chuyên biệt và schema cho thủ tục hành chính.
- `ui/`: Giao diện Web chuyên biệt cho công dân & cán bộ một cửa.

## Khởi chạy
Đảm bảo đã kích hoạt môi trường Python 3.12:
```powershell
py -3.12 backend/main.py
```
Mở trình duyệt tại: `http://127.0.0.1:8003`
