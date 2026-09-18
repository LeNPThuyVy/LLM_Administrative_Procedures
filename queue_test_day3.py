import asyncio

from backend.services.queue_service import queue_manager


async def fake_request(session_id: str, seconds: int = 2):
    session_lock = queue_manager.get_session_lock(session_id)

    async with session_lock:
        async with queue_manager.semaphore:
            print(f"[TEST] {session_id} START")

            await asyncio.sleep(seconds)

            print(f"[TEST] {session_id} DONE")


async def test_different_sessions():
    print("\n=== TEST 1: DIFFERENT SESSIONS ===")

    await asyncio.gather(
        fake_request("SESSION-001"),
        fake_request("SESSION-002"),
        fake_request("SESSION-003"),
        fake_request("SESSION-004"),
    )


async def test_same_session():
    print("\n=== TEST 2: SAME SESSION ===")

    await asyncio.gather(
        fake_request("SAME-SESSION"),
        fake_request("SAME-SESSION"),
    )


async def main():
    await test_different_sessions()
    await test_same_session()


if __name__ == "__main__":
    asyncio.run(main())