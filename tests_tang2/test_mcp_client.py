import asyncio
from types import SimpleNamespace

import pytest

import mcp_layer.client as client


@pytest.fixture(autouse=True)
def reset_state():
    client.reset_client_state()
    yield
    client.reset_client_state()


def admin_runtime():
    return SimpleNamespace(
        domain_id="administrative_procedures",
        allowed_tools=[
            "get_procedure_detail",
        ],
    )


def test_wrong_domain_blocked():
    runtime = SimpleNamespace(
        domain_id="administrative_procedures",
        allowed_tools=[
            "get_weather",
        ],
    )

    with pytest.raises(PermissionError):
        asyncio.run(
            client.call_tool(
                runtime,
                "get_weather",
                {
                    "city": "Ho Chi Minh City",
                },
            )
        )


def test_cache(monkeypatch):
    calls = {"count": 0}

    async def fake_remote(
        tool_name,
        args,
    ):
        calls["count"] += 1

        return {
            "success": True,
            "value": "ok",
        }

    monkeypatch.setattr(
        client,
        "_call_remote_tool",
        fake_remote,
    )

    runtime = admin_runtime()

    async def run():
        first = await client.call_tool(
            runtime,
            "get_procedure_detail",
            {
                "document_id": "PROC_001",
            },
        )

        second = await client.call_tool(
            runtime,
            "get_procedure_detail",
            {
                "document_id": "PROC_001",
            },
        )

        return first, second

    first, second = asyncio.run(run())

    assert first == second
    assert calls["count"] == 1


def test_circuit_breaker(monkeypatch):
    async def failing_remote(
        tool_name,
        args,
    ):
        raise RuntimeError(
            "simulated failure"
        )

    monkeypatch.setattr(
        client,
        "_call_remote_tool",
        failing_remote,
    )

    runtime = admin_runtime()

    async def run():
        for index in range(3):
            with pytest.raises(RuntimeError):
                await client.call_tool(
                    runtime,
                    "get_procedure_detail",
                    {
                        "document_id":
                        f"PROC_00{index + 1}",
                    },
                )

        with pytest.raises(
            RuntimeError,
            match="Circuit breaker is open",
        ):
            await client.call_tool(
                runtime,
                "get_procedure_detail",
                {
                    "document_id":
                    "PROC_004",
                },
            )

    asyncio.run(run())


def test_timeout(monkeypatch):
    async def slow_remote(
        tool_name,
        args,
    ):
        await asyncio.sleep(10)

    monkeypatch.setattr(
        client,
        "_call_remote_tool",
        slow_remote,
    )

    runtime = admin_runtime()

    old_timeout = (
        client.DEFAULT_TIMEOUT_SECONDS
    )

    client.DEFAULT_TIMEOUT_SECONDS = 0.01

    try:
        with pytest.raises(
            asyncio.TimeoutError
        ):
            asyncio.run(
                client.call_tool(
                    runtime,
                    "get_procedure_detail",
                    {
                        "document_id":
                        "PROC_001",
                    },
                )
            )
    finally:
        client.DEFAULT_TIMEOUT_SECONDS = (
            old_timeout
        )