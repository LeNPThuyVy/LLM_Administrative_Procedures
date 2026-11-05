import os
from urllib.parse import urlparse
from mcp_layer.tools.procedure import get_procedure_detail_data
from mcp.server.fastmcp import FastMCP
from mcp_layer.tools.official_procedure import (
    lookup_official_procedure_data,
)
from mcp_layer.tools.weather import get_weather_data

SERVER_NAME = "LLM Administrative Procedures MCP"

MCP_SERVER_URL = os.getenv(
    "MCP_SERVER_URL",
    "http://127.0.0.1:8001/mcp",
)

parsed_url = urlparse(MCP_SERVER_URL)

MCP_HOST = parsed_url.hostname or "127.0.0.1"
MCP_PORT = parsed_url.port or 8001

mcp = FastMCP(
    SERVER_NAME,
    host=MCP_HOST,
    port=MCP_PORT,
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def health_check() -> dict:
    """
    Kiểm tra MCP server đang hoạt động.

    Tool chỉ đọc, không thay đổi dữ liệu hệ thống.
    """
    return {
        "status": "ok",
        "service": SERVER_NAME,
        "read_only": True,
    }
@mcp.tool()
def get_procedure_detail(document_id: str) -> dict:
    """
    Lấy chi tiết một thủ tục hành chính theo document_id.

    Tool chỉ đọc dữ liệu cục bộ, không thay đổi trạng thái hệ thống.
    """
    return get_procedure_detail_data(document_id)

def main() -> None:
    print(f"[MCP] Starting server: {SERVER_NAME}")
    print(f"[MCP] Endpoint: {MCP_SERVER_URL}")

    mcp.run(
        transport="streamable-http",
    )

@mcp.tool()
def get_weather(city: str) -> dict:
    """
    Lấy thông tin thời tiết hiện tại theo thành phố.

    Tool chỉ đọc dữ liệu từ API công khai.
    """
    return get_weather_data(city)

@mcp.tool()
def lookup_official_procedure(name: str) -> dict:
    """
    Tra cứu thủ tục hành chính từ nguồn chính thức.

    Tool read-only.
    """
    return lookup_official_procedure_data(name)
if __name__ == "__main__":
    main()