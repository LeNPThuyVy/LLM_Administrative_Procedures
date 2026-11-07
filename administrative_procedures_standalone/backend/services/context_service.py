import asyncio
import time
import traceback

from context.context_service import (
    get_context as real_get_context,
    update_memory as real_update_memory,
)


MEMORY_RETRY_ATTEMPTS = 3
MEMORY_RETRY_BASE_DELAY_SECONDS = 0.5
MEMORY_DRAIN_TIMEOUT_SECONDS = 10.0

# Giữ reference để event loop không thu hồi task đang chạy.
_pending_memory_tasks: set[asyncio.Task] = set()


async def get_context(session_id: str, query: str):
    return await real_get_context(
        session_id=session_id,
        query=query
    )


async def update_memory(
    session_id: str,
    query: str,
    final_result: dict
):
    await real_update_memory(
        session_id=session_id,
        query=query,
        final_result=final_result
    )


async def _update_memory_with_retry(
    session_id: str,
    query: str,
    final_result: dict
):
    """
    Thử lại khi lỗi tạm thời. An toàn vì update_memory chỉ commit tin nhắn
    một lần ở cuối, lỗi giữa chừng được rollback nên không ghi trùng.
    """
    for attempt in range(1, MEMORY_RETRY_ATTEMPTS + 1):
        t0 = time.time()
        try:
            await update_memory(
                session_id=session_id,
                query=query,
                final_result=final_result
            )
            print(f"[time] update_memory = {time.time() - t0:.2f}s")
            return
        except Exception as exc:
            print(
                f"[MEMORY] session={session_id} "
                f"attempt {attempt}/{MEMORY_RETRY_ATTEMPTS} failed: {exc!r}"
            )
            if attempt == MEMORY_RETRY_ATTEMPTS:
                print(
                    f"[MEMORY] session={session_id} "
                    "mất lượt hội thoại này sau khi hết số lần thử"
                )
                traceback.print_exc()
                return
            await asyncio.sleep(
                MEMORY_RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1)
            )


def schedule_memory_update(
    session_id: str,
    query: str,
    final_result: dict
) -> asyncio.Task:
    task = asyncio.create_task(
        _update_memory_with_retry(
            session_id=session_id,
            query=query,
            final_result=final_result
        )
    )
    _pending_memory_tasks.add(task)
    task.add_done_callback(_pending_memory_tasks.discard)
    return task


async def drain_memory_updates(
    timeout: float = MEMORY_DRAIN_TIMEOUT_SECONDS
) -> None:
    """Chờ các lượt ghi đang chạy khi tắt server."""
    if _pending_memory_tasks:
        await asyncio.wait(set(_pending_memory_tasks), timeout=timeout)
