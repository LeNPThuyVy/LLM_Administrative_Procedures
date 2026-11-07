import asyncio

import pytest

import backend.services.context_service as service


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(service, "MEMORY_RETRY_BASE_DELAY_SECONDS", 0)


def recorder(failures):
    calls = []

    async def fake_update_memory(**kwargs):
        calls.append(kwargs)
        if len(calls) <= failures:
            raise RuntimeError("database tạm thời lỗi")

    return calls, fake_update_memory


def schedule():
    return service.schedule_memory_update(
        session_id="s",
        query="q",
        final_result={"answer": "a"},
    )


@pytest.mark.asyncio
async def test_transient_failure_is_retried(monkeypatch):
    calls, fake = recorder(failures=2)
    monkeypatch.setattr(service, "update_memory", fake)

    await schedule()

    assert len(calls) == 3


@pytest.mark.asyncio
async def test_retry_stops_after_limit_and_reports(monkeypatch, capsys):
    calls, fake = recorder(failures=99)
    monkeypatch.setattr(service, "update_memory", fake)

    await schedule()

    assert len(calls) == service.MEMORY_RETRY_ATTEMPTS
    assert "mất lượt hội thoại" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_success_keeps_timing_log_for_benchmark(monkeypatch, capsys):
    _, fake = recorder(failures=0)
    monkeypatch.setattr(service, "update_memory", fake)

    await schedule()

    assert "[time] update_memory = " in capsys.readouterr().out


@pytest.mark.asyncio
async def test_pending_task_is_tracked_until_done(monkeypatch):
    release = asyncio.Event()

    async def slow_update_memory(**_kwargs):
        await release.wait()

    monkeypatch.setattr(service, "update_memory", slow_update_memory)

    task = schedule()
    await asyncio.sleep(0)

    assert task in service._pending_memory_tasks

    release.set()
    await task
    await asyncio.sleep(0)

    assert task not in service._pending_memory_tasks


@pytest.mark.asyncio
async def test_drain_waits_for_pending_updates(monkeypatch):
    finished = []

    async def slow_update_memory(**_kwargs):
        await asyncio.sleep(0.01)
        finished.append(True)

    monkeypatch.setattr(service, "update_memory", slow_update_memory)

    schedule()
    await service.drain_memory_updates()

    assert finished == [True]


@pytest.mark.asyncio
async def test_drain_returns_when_nothing_is_pending():
    await service.drain_memory_updates()
