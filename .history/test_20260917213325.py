import requests

VAST_URL = "DÁN_TUNNEL_URL_CỦA_CẬU_VÀO_ĐÂY"

prompt = """
Bạn là trợ lý AI hỗ trợ thủ tục hành chính.

Hãy trả lời câu hỏi CHỈ dựa trên EVIDENCE.

QUY TẮC:
1. Chỉ sử dụng thông tin được nêu trong EVIDENCE.
2. Không sử dụng kiến thức bên ngoài.
3. Không tự suy đoán hoặc bổ sung thông tin.
4. Nếu EVIDENCE không đủ, hãy nói:
"Thông tin trong tài liệu chưa đủ để trả lời câu hỏi này."
5. Trả lời ngắn gọn bằng tiếng Việt.

EVIDENCE:
Thủ tục cấp bản sao giấy tờ hộ tịch yêu cầu người dân chuẩn bị:
- Tờ khai yêu cầu cấp bản sao.
- Căn cước công dân hoặc giấy tờ tùy thân hợp lệ.

CÂU HỎI:
Người dân cần chuẩn bị những gì để thực hiện thủ tục này?
"""

response = requests.post(
    f"{VAST_URL}/generate",
    json={"prompt": prompt},
    timeout=120,
)

print("Status:", response.status_code)
print("Answer:", response.json()["answer"])