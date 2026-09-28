import asyncio
import httpx

API_URL = "http://127.0.0.1:8000/api/chat"

sessions = [
    "11887286-da3b-4cb7-a351-f498eb9b3496",
    "e122b4e5-280c-49aa-a15f-a6e7f5d42731",
    "d0d00669-f8ad-4f67-87e0-def1c95af1f3",
    "d6d80968-6dfd-42cd-9d2e-620a23dc567d",
]

queries = [
    "Tôi cần đăng ký kết hôn",
    "Tôi cần làm giấy khai sinh",
    "Tôi muốn đăng ký tạm trú",
    "Tôi cần đăng ký hộ kinh doanh",
]


async def send_request(session_id, query):
    async with httpx.AsyncClient(timeout=300) as client:
        print(f"[CLIENT] {session_id} START")

        async with client.stream(
            "POST",
            API_URL,
            json={
                "session_id": session_id,
                "query": query,
            },
        ) as response:

            print(
                f"[CLIENT] {session_id} STATUS {response.status_code}"
            )

            async for line in response.aiter_lines():
                if line.startswith("event: done"):
                    print(f"[CLIENT] {session_id} DONE")

        print(f"[CLIENT] {session_id} FINISH")


async def main():
    await asyncio.gather(
        *[
            send_request(session_id, query)
            for session_id, query in zip(sessions, queries)
        ]
    )


if __name__ == "__main__":
    asyncio.run(main())