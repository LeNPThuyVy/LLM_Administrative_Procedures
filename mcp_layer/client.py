import asyncio
import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from mcp_layer.registry import (
    get_tool_definition,
    is_tool_allowed,
)


MCP_SERVER_URL = os.getenv(
    "MCP_SERVER_URL",
    "http://127.0.0.1:8001/mcp",
)

DEFAULT_TIMEOUT_SECONDS = 5.0
BREAKER_FAILURE_THRESHOLD = 3
BREAKER_OPEN_SECONDS = 60

_CACHE_MAX_SIZE = 128


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


@dataclass
class BreakerState:
    consecutive_failures: int = 0
    opened_at: float | None = None


_cache: OrderedDict[str, CacheEntry] = OrderedDict()
_breakers: dict[str, BreakerState] = {}


def _make_cache_key(
    domain: str,
    tool_name: str,
    args: dict[str, Any],
) -> str:
    payload = json.dumps(
        args,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return f"{domain}:{tool_name}:{payload}"


def _get_cached_value(cache_key: str) -> Any | None:
    entry = _cache.get(cache_key)

    if entry is None:
        return None

    now = time.monotonic()

    if now >= entry.expires_at:
        _cache.pop(cache_key, None)
        return None

    _cache.move_to_end(cache_key)
    return entry.value


def _set_cached_value(
    cache_key: str,
    value: Any,
    ttl_seconds: int,
) -> None:
    _cache[cache_key] = CacheEntry(
        value=value,
        expires_at=time.monotonic() + ttl_seconds,
    )

    _cache.move_to_end(cache_key)

    while len(_cache) > _CACHE_MAX_SIZE:
        _cache.popitem(last=False)


def _get_breaker(tool_name: str) -> BreakerState:
    if tool_name not in _breakers:
        _breakers[tool_name] = BreakerState()

    return _breakers[tool_name]


def _is_breaker_open(tool_name: str) -> bool:
    state = _get_breaker(tool_name)

    if state.opened_at is None:
        return False

    elapsed = time.monotonic() - state.opened_at

    if elapsed >= BREAKER_OPEN_SECONDS:
        state.opened_at = None
        state.consecutive_failures = 0
        return False

    return True


def _record_success(tool_name: str) -> None:
    state = _get_breaker(tool_name)
    state.consecutive_failures = 0
    state.opened_at = None


def _record_failure(tool_name: str) -> None:
    state = _get_breaker(tool_name)

    state.consecutive_failures += 1

    if state.consecutive_failures >= BREAKER_FAILURE_THRESHOLD:
        state.opened_at = time.monotonic()


def _log_call(
    *,
    tool: str,
    domain: str,
    duration_ms: float,
    success: bool,
    cached: bool = False,
    error: str | None = None,
) -> None:
    payload = {
        "tool": tool,
        "domain": domain,
        "duration_ms": round(duration_ms, 2),
        "success": success,
        "cached": cached,
    }

    if error:
        payload["error"] = error

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
        )
    )


async def _call_remote_tool(
    tool_name: str,
    args: dict[str, Any],
) -> Any:
    async with streamablehttp_client(
        MCP_SERVER_URL
    ) as streams:
        read_stream, write_stream, _ = streams

        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:
            await session.initialize()

            result = await session.call_tool(
                tool_name,
                arguments=args,
            )

            if getattr(result, "isError", False):
                raise RuntimeError(
                    f"MCP tool returned error: {tool_name}"
                )

            structured = getattr(
                result,
                "structuredContent",
                None,
            )

            if structured is not None:
                return structured

            content = getattr(result, "content", None)

            if content is None:
                return None

            values = []

            for item in content:
                text = getattr(item, "text", None)

                if text is None:
                    continue

                try:
                    values.append(json.loads(text))
                except json.JSONDecodeError:
                    values.append(text)

            if len(values) == 1:
                return values[0]

            return values


async def call_tool(
    runtime,
    name: str,
    args: dict[str, Any],
) -> Any:
    """
    Gọi tool qua MCP.

    Quy trình:
    1. kiểm tra registry + quyền domain
    2. circuit breaker
    3. cache TTL
    4. gọi MCP với timeout
    5. log JSON một dòng
    """
    started_at = time.monotonic()

    domain = getattr(
        runtime,
        "domain_id",
        "",
    )

    try:
        definition = get_tool_definition(name)
    except ValueError as exc:
        duration = (
            time.monotonic() - started_at
        ) * 1000

        _log_call(
            tool=name,
            domain=domain,
            duration_ms=duration,
            success=False,
            error=str(exc),
        )

        raise

    if not is_tool_allowed(runtime, name):
        duration = (
            time.monotonic() - started_at
        ) * 1000

        error = (
            f"Tool '{name}' is not allowed "
            f"for domain '{domain}'"
        )

        _log_call(
            tool=name,
            domain=domain,
            duration_ms=duration,
            success=False,
            error=error,
        )

        raise PermissionError(error)

    if _is_breaker_open(name):
        duration = (
            time.monotonic() - started_at
        ) * 1000

        error = (
            f"Circuit breaker is open "
            f"for tool '{name}'"
        )

        _log_call(
            tool=name,
            domain=domain,
            duration_ms=duration,
            success=False,
            error=error,
        )

        raise RuntimeError(error)

    cache_key = _make_cache_key(
        domain,
        name,
        args,
    )

    cached_value = _get_cached_value(
        cache_key
    )

    if cached_value is not None:
        duration = (
            time.monotonic() - started_at
        ) * 1000

        _log_call(
            tool=name,
            domain=domain,
            duration_ms=duration,
            success=True,
            cached=True,
        )

        return cached_value

    timeout_seconds = min(
        definition.timeout_seconds,
        DEFAULT_TIMEOUT_SECONDS,
    )

    try:
        result = await asyncio.wait_for(
            _call_remote_tool(
                name,
                args,
            ),
            timeout=timeout_seconds,
        )

        _record_success(name)

        _set_cached_value(
            cache_key,
            result,
            definition.cache_ttl_seconds,
        )

        duration = (
            time.monotonic() - started_at
        ) * 1000

        _log_call(
            tool=name,
            domain=domain,
            duration_ms=duration,
            success=True,
            cached=False,
        )

        return result

    except Exception as exc:
        _record_failure(name)

        duration = (
            time.monotonic() - started_at
        ) * 1000

        _log_call(
            tool=name,
            domain=domain,
            duration_ms=duration,
            success=False,
            cached=False,
            error=str(exc),
        )

        raise


def reset_client_state() -> None:
    """
    Chỉ dùng cho test:
    xóa cache và reset circuit breaker.
    """
    _cache.clear()
    _breakers.clear()