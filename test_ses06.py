import asyncio
import uuid
import httpx

BASE_URL = "http://127.0.0.1:8000/api/session/bootstrap"


async def call_bootstrap(client, i):
    response = await client.get(BASE_URL)
    print(
        f"Request {i}: "
        f"status={response.status_code}, "
        f"body={response.text}"
    )


async def main():
    session_id = str(uuid.uuid4())

    print("Test UUID:", session_id)

    cookies = {
        "session_id": session_id
    }

    async with httpx.AsyncClient(
        cookies=cookies,
        timeout=30
    ) as client:
        await asyncio.gather(
            *[
                call_bootstrap(client, i)
                for i in range(1, 6)
            ]
        )


asyncio.run(main())