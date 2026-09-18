import requests

VAST_URL = "DÁN_TUNNEL_URL_CỦA_CẬU_VÀO_ĐÂY"

response = requests.post(
    f"{VAST_URL}/generate",
    json={
        "prompt": "Người dân muốn thực hiện một thủ tục hành chính thì cần chuẩn bị những gì?"
    },
    timeout=120,
)

print("Status:", response.status_code)
print("Answer:", response.json()["answer"])