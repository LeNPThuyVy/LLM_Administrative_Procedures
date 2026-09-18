import requests

VAST_URL = "https://passengers-indiana-discussions-zus.trycloudflare.com"

response = requests.post(
    f"{VAST_URL}/generate",
    json={
        "prompt": "Người dân muốn thực hiện một thủ tục hành chính thì cần chuẩn bị những gì?"
    },
    timeout=120,
)

print("Status:", response.status_code)
print("Answer:", response.json()["answer"])