from rag.hybrid_generator import generate_hybrid

answer = generate_hybrid(
    """
EVIDENCE:
Thủ tục cấp bản sao giấy tờ hộ tịch yêu cầu người dân chuẩn bị:
- Tờ khai yêu cầu cấp bản sao.
- Căn cước công dân hoặc giấy tờ tùy thân hợp lệ.

CÂU HỎI:
Người dân cần chuẩn bị những gì?
"""
)

print("\n=== ANSWER ===")
print(answer)