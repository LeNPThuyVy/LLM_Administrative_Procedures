import asyncio
from types import SimpleNamespace

import mcp_layer.bridge as bridge


def test_tool_failure_returns_empty(
    monkeypatch,
):
    async def failing_call(
        runtime,
        name,
        args,
    ):
        raise RuntimeError(
            "MCP unavailable"
        )

    monkeypatch.setattr(
        bridge,
        "call_tool",
        failing_call,
    )

    runtime = SimpleNamespace(
        domain_id="administrative_procedures",
        mode="friendly",
        allowed_tools=[
            "get_procedure_detail",
        ],
    )

    result = asyncio.run(
        bridge.run_tools(
            "Cho tôi chi tiết thủ tục PROC_001",
            runtime,
            {},
        )
    )

    assert result == []


def test_weather_friendly(
    monkeypatch,
):
    async def fake_call(
        runtime,
        name,
        args,
    ):
        return {
            "success": True,
            "result": {
                "city": "Ho Chi Minh City",
                "temperature_c": 30.0,
            },
        }

    monkeypatch.setattr(
        bridge,
        "call_tool",
        fake_call,
    )

    runtime = SimpleNamespace(
        domain_id="tourism",
        mode="friendly",
        allowed_tools=[
            "get_weather",
        ],
    )

    result = asyncio.run(
        bridge.run_tools(
            (
                "Th\u1eddi ti\u1ebft \u1edf "
                "Ho Chi Minh City "
                "h\u00f4m nay?"
            ),
            runtime,
            {},
        )
    )

    assert len(result) == 1
    assert (
        result[0].source
        == "tool:get_weather"
    )


def test_weather_strict_blocked():
    runtime = SimpleNamespace(
        domain_id="tourism",
        mode="strict",
        allowed_tools=[
            "get_weather",
        ],
    )

    result = asyncio.run(
        bridge.run_tools(
            (
                "Th\u1eddi ti\u1ebft \u1edf "
                "Ho Chi Minh City "
                "h\u00f4m nay?"
            ),
            runtime,
            {},
        )
    )

    assert result == []