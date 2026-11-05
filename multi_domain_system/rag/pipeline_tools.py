from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from mcp_layer.bridge import run_tools

logger = logging.getLogger(__name__)


def run_tools_sync(
    query: str,
    runtime,
    context: dict | None,
):
    """Gọi async MCP từ pipeline sync.

    Nếu đang ở trong event loop của FastAPI/WebSocket,
    chạy coroutine trong thread riêng.
    """
    async def _runner():
        return await run_tools(
            query=query,
            runtime=runtime,
            context=context,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_runner())

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: asyncio.run(_runner()))
        return future.result(timeout=10)


def build_tool_calls(tool_evidence) -> list[dict]:
    """Convert MCP evidence thành metadata tool_calls để backend/UI có thể trả về client."""
    return [
        {
            "tool": ev.source.removeprefix("tool:"),
            "candidate_id": ev.candidate_id,
            "document_id": ev.document_id,
            "source_url": ev.source_url,
        }
        for ev in tool_evidence
        if getattr(ev, "source", "").startswith("tool:")
    ]
