import asyncio
import json
import time

import httpx
import websockets


BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws/chat"

QUERY = "Đăng ký khai sinh cần giấy tờ gì?"


async def create_session(index: int):
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/api/session/bootstrap")
        response.raise_for_status()

        data = response.json()
        session_id = data["session_id"]

        print(f"[SESSION {index}] {session_id}")
        return session_id


async def run_one(index: int, session_id: str):
    headers = {
        "Cookie": f"session_id={session_id}"
    }

    start = time.perf_counter()

    try:
        async with websockets.connect(
            WS_URL,
            additional_headers=headers,
            open_timeout=20,
            close_timeout=10,
        ) as ws:

            first = json.loads(await ws.recv())

            if first.get("type") != "connected":
                print(f"[{index}] FAIL - không nhận connected: {first}")
                return False

            print(f"[{index}] CONNECTED")

            await ws.send(json.dumps({
                "query": QUERY
            }, ensure_ascii=False))

            evidence_count = 0
            chunk_count = 0

            while True:
                raw = await ws.recv()
                event = json.loads(raw)

                event_type = event.get("type")

                if event_type == "evidence":
                    evidence_count += 1

                elif event_type == "chunk":
                    chunk_count += 1

                elif event_type == "clarification":
                    print(f"[{index}] CLARIFICATION")

                elif event_type == "error":
                    print(f"[{index}] ERROR: {event}")
                    return False

                elif event_type == "done":
                    elapsed = time.perf_counter() - start

                    print(
                        f"[{index}] DONE | "
                        f"evidence={evidence_count} | "
                        f"chunks={chunk_count} | "
                        f"time={elapsed:.2f}s"
                    )

                    return True

    except Exception as e:
        print(f"[{index}] EXCEPTION: {type(e).__name__}: {e}")
        return False


async def main():
    print("=" * 70)
    print("WS-12 - 6 SESSION CONCURRENT TEST")
    print("=" * 70)

    # Tạo 6 session khác nhau
    session_ids = await asyncio.gather(
        *[create_session(i) for i in range(1, 7)]
    )

    print("\nBắt đầu gửi 6 request gần như đồng thời...\n")

    start_all = time.perf_counter()

    results = await asyncio.gather(
        *[
            run_one(i, session_ids[i - 1])
            for i in range(1, 7)
        ]
    )

    total_time = time.perf_counter() - start_all

    passed = sum(results)
    failed = len(results) - passed

    print("\n" + "=" * 70)
    print("KẾT QUẢ WS-12")
    print("=" * 70)
    print(f"PASS : {passed}/6")
    print(f"FAIL : {failed}/6")
    print(f"TOTAL: {total_time:.2f}s")

    if passed == 6:
        print("CLIENT RESULT: PASS - tất cả 6 session đều nhận DONE")
    else:
        print("CLIENT RESULT: FAIL - có session không hoàn thành")

    print("\nKiểm tra thêm terminal Uvicorn:")
    print("Phải thấy tối đa 3 request START cùng lúc trước khi có DONE.")


if __name__ == "__main__":
    asyncio.run(main())