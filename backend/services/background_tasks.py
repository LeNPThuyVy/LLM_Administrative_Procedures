from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# Keep strong references to background tasks to avoid garbage collection before completion
_ACTIVE_BACKGROUND_TASKS: set[asyncio.Task] = set()

# Exceptions that should fail fast without retry
DEFAULT_NON_RETRY_EXCEPTIONS = (
    TypeError,
    ValueError,
    KeyError,
    AttributeError,
    NotImplementedError,
)


async def _execute_with_retry(
    coro_fn: Callable[..., Coroutine[Any, Any, Any]],
    args: tuple,
    kwargs: dict,
    name: str,
    retries: int,
    base_delay: float,
    retry_exceptions: tuple[type[BaseException], ...],
    non_retry_exceptions: tuple[type[BaseException], ...],
) -> Any:
    for attempt in range(1, retries + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except non_retry_exceptions as exc:
            logger.exception(
                "[background_task:%s] Non-retryable error on attempt %d: %s",
                name,
                attempt,
                exc,
            )
            return None
        except retry_exceptions as exc:
            if attempt == retries:
                logger.exception(
                    "[background_task:%s] All %d attempts exhausted. Final failure: %s",
                    name,
                    retries,
                    exc,
                )
                return None

            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "[background_task:%s] Attempt %d failed: %s. Retrying in %.2fs...",
                name,
                attempt,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
        except BaseException as exc:
            logger.exception(
                "[background_task:%s] Unexpected critical error on attempt %d: %s",
                name,
                attempt,
                exc,
            )
            return None
    return None


def run_background_with_retry(
    coro_fn: Callable[..., Coroutine[Any, Any, Any]],
    *args: Any,
    name: str = "background_task",
    retries: int = 3,
    base_delay: float = 0.5,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
    non_retry_exceptions: tuple[type[BaseException], ...] = DEFAULT_NON_RETRY_EXCEPTIONS,
    **kwargs: Any,
) -> asyncio.Task:
    """
    Launch a reliable background asyncio Task with bounded retries and exponential backoff.

    Guarantees:
    1. Caller's request is not blocked (runs concurrently in background).
    2. Transient failures are retried with exponential backoff.
    3. Programming/validation errors fail fast without wasteful retries.
    4. Task failure never crashes the main request.
    5. All failures and exceptions are logged with stack traces (no silent swallowing).
    """
    task = asyncio.create_task(
        _execute_with_retry(
            coro_fn=coro_fn,
            args=args,
            kwargs=kwargs,
            name=name,
            retries=retries,
            base_delay=base_delay,
            retry_exceptions=retry_exceptions,
            non_retry_exceptions=non_retry_exceptions,
        ),
        name=f"bg_{name}",
    )

    _ACTIVE_BACKGROUND_TASKS.add(task)
    task.add_done_callback(_ACTIVE_BACKGROUND_TASKS.discard)
    return task

