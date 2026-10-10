import asyncio

from backend.services.queue_service import (
    QueueManager,
    QueueFullError,
)


TEST_CONCURRENCY = 3
TEST_QUEUE_SIZE = 12
TEST_TIMEOUT = 10.0


async def main():
    queue = QueueManager(
        max_concurrency=TEST_CONCURRENCY,
        max_queue_size=TEST_QUEUE_SIZE,
        queue_timeout=TEST_TIMEOUT,
    )

    release_running = asyncio.Event()

    running_started = asyncio.Event()
    running_count = 0
    running_lock = asyncio.Lock()

    async def running_worker(
        worker_id: int,
    ):
        nonlocal running_count

        async with queue.execution_slot():
            async with running_lock:
                running_count += 1

                print(
                    f"RUNNING {worker_id}: "
                    "acquired slot"
                )

                if (
                    running_count
                    == TEST_CONCURRENCY
                ):
                    running_started.set()

            await release_running.wait()

    async def waiting_worker(
        worker_id: int,
    ):
        try:
            async with queue.execution_slot():
                print(
                    f"WAITING {worker_id}: "
                    "eventually acquired"
                )

                return "acquired"

        except QueueFullError:
            print(
                f"WAITING {worker_id}: "
                "QUEUE FULL"
            )

            return "queue_full"

    # =====================================================
    # 1. Chiếm toàn bộ 3 execution slots
    # =====================================================

    running_tasks = [
        asyncio.create_task(
            running_worker(i)
        )
        for i in range(
            1,
            TEST_CONCURRENCY + 1,
        )
    ]

    await asyncio.wait_for(
        running_started.wait(),
        timeout=5,
    )

    print()
    print(
        f"Active slots occupied: "
        f"{TEST_CONCURRENCY}"
    )

    # =====================================================
    # 2. Đưa đúng 12 request vào waiting queue
    # =====================================================

    waiting_tasks = []

    for worker_id in range(
        1,
        TEST_QUEUE_SIZE + 1,
    ):
        task = asyncio.create_task(
            waiting_worker(
                worker_id
            )
        )

        waiting_tasks.append(task)

        # Cho task cơ hội vào acquire_slot()
        await asyncio.sleep(0.02)

    # Đợi queue ổn định
    for _ in range(100):
        if (
            queue.waiting_count
            == TEST_QUEUE_SIZE
        ):
            break

        await asyncio.sleep(0.02)

    print(
        f"Waiting queue size: "
        f"{queue.waiting_count}"
    )

    # =====================================================
    # 3. Request thứ 13 đang chờ phải bị QueueFullError
    # =====================================================

    overflow_result = None

    try:
        await queue.acquire_slot()

        overflow_result = (
            "unexpectedly_acquired"
        )

        queue.release_slot()

    except QueueFullError:
        overflow_result = "queue_full"

        print(
            "OVERFLOW REQUEST: "
            "QueueFullError"
        )

    print()
    print("=" * 60)
    print("QUEUE OVERLOAD RESULT")
    print("=" * 60)

    print(
        f"Max concurrency: "
        f"{TEST_CONCURRENCY}"
    )

    print(
        f"Max queue size: "
        f"{TEST_QUEUE_SIZE}"
    )

    print(
        f"Waiting count before overflow: "
        f"{queue.waiting_count}"
    )

    print(
        f"Overflow result: "
        f"{overflow_result}"
    )

    if overflow_result == "queue_full":
        print(
            "PASS: Queue từ chối request "
            "khi vượt giới hạn."
        )
    else:
        print(
            "FAIL: Queue không từ chối "
            "request vượt giới hạn."
        )

    print("=" * 60)

    # =====================================================
    # 4. Release 3 running slots để cleanup toàn bộ tasks
    # =====================================================

    release_running.set()

    await asyncio.gather(
        *running_tasks,
    )

    await asyncio.gather(
        *waiting_tasks,
    )

    print(
        f"Waiting count after cleanup: "
        f"{queue.waiting_count}"
    )

    if queue.waiting_count == 0:
        print(
            "PASS: Queue cleanup hoàn tất."
        )
    else:
        print(
            "FAIL: Queue còn request "
            "sau cleanup."
        )


if __name__ == "__main__":
    asyncio.run(
        main()
    )