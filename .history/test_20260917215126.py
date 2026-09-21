import rag.hybrid_generator as hybrid

original_remote = hybrid.generate_remote

def fake_remote(prompt):
    raise ConnectionError("Simulated remote failure")


hybrid.generate_remote = fake_remote


answer = hybrid.generate_hybrid(
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


# Khôi phục lại remote generator
hybrid.generate_remote = original_remote