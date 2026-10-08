from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    domains: tuple[str, ...]
    timeout_seconds: float
    cache_ttl_seconds: int
    official: bool = False


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "get_procedure_detail": ToolDefinition(
        name="get_procedure_detail",
        description="Lấy chi tiết thủ tục hành chính theo document_id.",
        domains=("administrative_procedures",),
        timeout_seconds=5.0,
        cache_ttl_seconds=300,
        official=True,
    ),
    "lookup_official_procedure": ToolDefinition(
        name="lookup_official_procedure",
        description="Tra cứu thủ tục từ nguồn Dịch vụ công chính thức.",
        domains=("administrative_procedures",),
        timeout_seconds=5.0,
        cache_ttl_seconds=300,
        official=True,
    ),
    "get_weather": ToolDefinition(
        name="get_weather",
        description="Lấy thời tiết hiện tại theo thành phố.",
        domains=("tourism", "tourism_demo"),
        timeout_seconds=5.0,
        cache_ttl_seconds=600,
        official=False,
    ),
}


def get_tool_definition(name: str) -> ToolDefinition:
    try:
        return TOOL_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown tool: {name}") from exc


def get_domain_allowed_tools(runtime) -> set[str]:
    """
    Lấy danh sách tool được DomainRuntime cho phép.

    runtime được kỳ vọng có:
        domain_id
        allowed_tools
    """
    allowed = getattr(runtime, "allowed_tools", None)

    if allowed is None:
        return set()

    return {str(name) for name in allowed}


def is_tool_allowed(runtime, tool_name: str) -> bool:
    """
    Kiểm tra đồng thời:
    1. tool có trong registry;
    2. domain của runtime nằm trong domains khai báo của tool;
    3. tool có trong runtime.allowed_tools.
    """
    definition = get_tool_definition(tool_name)

    domain_id = getattr(runtime, "domain_id", None)
    if not domain_id:
        return False

    if domain_id not in definition.domains:
        return False

    allowed_tools = get_domain_allowed_tools(runtime)
    if tool_name not in allowed_tools:
        return False

    return True


def list_tools_for_runtime(runtime) -> list[ToolDefinition]:
    return [
        definition
        for definition in TOOL_REGISTRY.values()
        if is_tool_allowed(runtime, definition.name)
    ]


def validate_allowed_tools(
    domain_id: str,
    allowed_tools: Iterable[str],
) -> list[str]:
    """
    Trả về các tool cấu hình sai:
    - không tồn tại trong registry
    - hoặc không thuộc domain tương ứng
    """
    invalid: list[str] = []

    for name in allowed_tools:
        definition = TOOL_REGISTRY.get(name)

        if definition is None:
            invalid.append(name)
            continue

        if domain_id not in definition.domains:
            invalid.append(name)

    return invalid