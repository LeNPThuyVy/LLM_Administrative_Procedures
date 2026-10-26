import json
import re
from typing import Any

from mcp_layer.client import call_tool
from mcp_layer.registry import get_tool_definition
from rag.evidence_builder import (
    EvidenceCandidate,
    build_tool_evidence_candidate,
)


WEATHER_KEYWORDS = (
    "thời tiết",
    "nhiệt độ",
    "weather",
    "temperature",
)

OFFICIAL_PROCEDURE_KEYWORDS = (
    "dịch vụ công",
    "cổng dịch vụ công",
    "nguồn chính thức",
    "thông tin chính thức",
    "tra cứu chính thức",
)

PROCEDURE_DETAIL_KEYWORDS = (
    "chi tiết thủ tục",
    "thông tin thủ tục",
    "procedure detail",
)


def _normalize(text: str) -> str:
    return str(text or "").strip().lower()


def _extract_document_id(
    query: str,
    context: dict | None,
) -> str | None:
    match = re.search(
        r"\bPROC_\d+\b",
        query,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(0).upper()

    if context:
        document_id = context.get("document_id")
        if document_id:
            return str(document_id)

    return None


def _extract_weather_city(
    query: str,
    context: dict | None,
) -> str | None:
    if context:
        for key in ("city", "location"):
            value = context.get(key)
            if value:
                return str(value).strip()

    text = query.strip()

    patterns = (
        r"(?:thời tiết|nhiệt độ)\s+(?:ở|tại)?\s*([^?.,]+)",
        r"(?:weather|temperature)\s+(?:in|at)?\s*([^?.,]+)",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        city = match.group(1).strip()

        # Bỏ một số từ cuối câu thường gặp.
        city = re.sub(
            r"\b(hôm nay|hiện tại|bây giờ|today|now)\b.*$",
            "",
            city,
            flags=re.IGNORECASE,
        ).strip()

        if city:
            return city

    return None


def _tool_result_to_content(result: Any) -> str:
    if isinstance(result, str):
        return result

    return json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        default=str,
    )


def _result_metadata(
    tool_name: str,
    result: Any,
) -> tuple[str, str, str | None]:
    """
    Return:
        title, document_id, source_url
    """
    title = tool_name
    document_id = ""
    source_url = None

    if not isinstance(result, dict):
        return title, document_id, source_url

    document = result.get("document")

    if isinstance(document, dict):
        title = str(
            document.get("title")
            or tool_name
        )
        document_id = str(
            document.get("document_id")
            or ""
        )
        source_url = (
            document.get("source_url")
            or None
        )

    tool_result = result.get("result")

    if isinstance(tool_result, dict):
        title = str(
            tool_result.get("title")
            or tool_result.get("city")
            or title
        )

        source_url = (
            tool_result.get("official_url")
            or source_url
        )

    source_url = (
        result.get("search_url")
        or source_url
    )

    return title, document_id, source_url


def _select_tool_calls(
    query: str,
    runtime,
    context: dict | None,
) -> list[tuple[str, dict[str, Any]]]:
    """
    Keyword-rule tool selection.

    This deliberately remains simple and deterministic.
    """
    normalized = _normalize(query)

    allowed_tools = set(
        getattr(runtime, "allowed_tools", [])
        or []
    )

    selected: list[tuple[str, dict[str, Any]]] = []

    # 1. Procedure detail by explicit/current document_id.
    document_id = _extract_document_id(
        query,
        context,
    )

    wants_detail = (
        document_id is not None
        and (
            any(
                keyword in normalized
                for keyword in PROCEDURE_DETAIL_KEYWORDS
            )
            or "get_procedure_detail" in allowed_tools
        )
    )

    if (
        wants_detail
        and "get_procedure_detail" in allowed_tools
    ):
        selected.append(
            (
                "get_procedure_detail",
                {"document_id": document_id},
            )
        )

    # 2. Official procedure lookup.
    if (
        "lookup_official_procedure"
        in allowed_tools
        and any(
            keyword in normalized
            for keyword in OFFICIAL_PROCEDURE_KEYWORDS
        )
    ):
        selected.append(
            (
                "lookup_official_procedure",
                {"name": query.strip()},
            )
        )

    # 3. Weather.
    if (
        "get_weather" in allowed_tools
        and any(
            keyword in normalized
            for keyword in WEATHER_KEYWORDS
        )
    ):
        city = _extract_weather_city(
            query,
            context,
        )

        if city:
            selected.append(
                (
                    "get_weather",
                    {"city": city},
                )
            )

    return selected


async def run_tools(
    query: str,
    runtime,
    context: dict | None = None,
) -> list[EvidenceCandidate]:
    """
    Run applicable MCP tools and convert successful results
    into EvidenceCandidate objects.

    Behaviour required by Layer 3 plan:
    - domain allow-list is respected
    - strict mode accepts only official tools
    - tool failures/timeouts are swallowed
    - normal RAG pipeline can continue when MCP is unavailable
    """
    selected = _select_tool_calls(
        query,
        runtime,
        context,
    )

    if not selected:
        return []

    evidence: list[EvidenceCandidate] = []

    strict_mode = (
        str(
            getattr(runtime, "mode", "friendly")
        ).lower()
        == "strict"
    )

    for tool_name, args in selected:
        try:
            definition = get_tool_definition(
                tool_name
            )

            # Strict: only official tool evidence.
            if strict_mode and not definition.official:
                continue

            result = await call_tool(
                runtime,
                tool_name,
                args,
            )

            # Tool itself may return a graceful failure.
            if (
                isinstance(result, dict)
                and result.get("success") is False
            ):
                continue

            content = _tool_result_to_content(
                result
            )

            title, document_id, source_url = (
                _result_metadata(
                    tool_name,
                    result,
                )
            )

            candidate = (
                build_tool_evidence_candidate(
                    index=len(evidence) + 1,
                    tool_name=tool_name,
                    content=content,
                    title=title,
                    document_id=document_id,
                    source_url=source_url,
                )
            )

            evidence.append(candidate)

        except Exception:
            # MCP/tool failure must never break the RAG request.
            continue

    return evidence