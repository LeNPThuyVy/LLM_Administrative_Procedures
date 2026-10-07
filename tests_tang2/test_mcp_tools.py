import os

from mcp_layer.tools.official_procedure import (
    lookup_official_procedure_data,
)
from mcp_layer.tools.procedure import (
    get_procedure_detail_data,
)
from mcp_layer.tools.weather import (
    get_weather_data,
)


def test_procedure_detail_found():
    result = get_procedure_detail_data(
        "PROC_001"
    )

    assert result["success"] is True
    assert (
        result["document"]["document_id"]
        == "PROC_001"
    )


def test_procedure_detail_not_found():
    result = get_procedure_detail_data(
        "PROC_999"
    )

    assert result["success"] is False


def test_official_procedure_mock():
    os.environ["MCP_MOCK"] = "1"

    result = lookup_official_procedure_data(
        "Đăng ký thường trú"
    )

    assert result["success"] is True
    assert result["mock"] is True
    assert result["official"] is True


def test_weather_mock():
    os.environ["MCP_MOCK"] = "1"

    result = get_weather_data(
        "Ho Chi Minh City"
    )

    assert result["success"] is True
    assert result["mock"] is True