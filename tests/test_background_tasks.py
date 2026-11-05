import asyncio
import pytest
from backend.services.background_tasks import run_background_with_retry


@pytest.mark.asyncio
async def test_background_task_success():
    call_count = 0

    async def sample_op(x: int):
        nonlocal call_count
        call_count += 1
        return x * 2

    task = run_background_with_retry(sample_op, 5, name="test_success")
    await task
    assert call_count == 1


@pytest.mark.asyncio
async def test_background_task_transient_retry():
    call_count = 0

    async def flaky_op():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionResetError("Transient network drop")
        return "ok"

    task = run_background_with_retry(flaky_op, name="test_flaky", retries=3, base_delay=0.01)
    await task
    assert call_count == 3


@pytest.mark.asyncio
async def test_background_task_exhausted():
    call_count = 0

    async def permanently_failing_op():
        nonlocal call_count
        call_count += 1
        raise ConnectionRefusedError("Database unreachable")

    task = run_background_with_retry(
        permanently_failing_op,
        name="test_exhausted",
        retries=3,
        base_delay=0.01,
    )
    await task
    assert call_count == 3


@pytest.mark.asyncio
async def test_background_task_non_retryable():
    call_count = 0

    async def bug_op():
        nonlocal call_count
        call_count += 1
        raise ValueError("Invalid schema parameter")

    task = run_background_with_retry(
        bug_op,
        name="test_non_retryable",
        retries=3,
        base_delay=0.01,
    )
    await task
    # Non-retryable error must not be retried
    assert call_count == 1

