from types import SimpleNamespace

from mcp_layer.registry import (
    is_tool_allowed,
    list_tools_for_runtime,
    validate_allowed_tools,
)


def test_admin_domain_tools():
    runtime = SimpleNamespace(
        domain_id="administrative_procedures",
        allowed_tools=[
            "get_procedure_detail",
            "lookup_official_procedure",
        ],
    )

    names = [
        tool.name
        for tool in list_tools_for_runtime(runtime)
    ]

    assert names == [
        "get_procedure_detail",
        "lookup_official_procedure",
    ]

    assert is_tool_allowed(
        runtime,
        "get_procedure_detail",
    )

    assert not is_tool_allowed(
        runtime,
        "get_weather",
    )


def test_tourism_domain_tools():
    runtime = SimpleNamespace(
        domain_id="tourism",
        allowed_tools=["get_weather"],
    )

    assert is_tool_allowed(
        runtime,
        "get_weather",
    )

    assert not is_tool_allowed(
        runtime,
        "get_procedure_detail",
    )


def test_invalid_tools():
    invalid = validate_allowed_tools(
        "administrative_procedures",
        [
            "get_weather",
            "ABC",
        ],
    )

    assert invalid == [
        "get_weather",
        "ABC",
    ]