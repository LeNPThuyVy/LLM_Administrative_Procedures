import asyncio
import sys

import httpx


BASE_URL = "http://127.0.0.1:8000"
TOTAL_REQUESTS = 25


async def get_session(
    client: httpx.AsyncClient,
) -> str:
    response = await client.get(
        f"{BASE_URL}/api/session/bootstrap"
    )

    response.raise_for_status()

    data = response.json()

    session_id = data.get("session_id")

    if not session_id:
        raise RuntimeError(
            "Không lấy được session_id"
        )

    return session_id


async def get_domain(
    client: httpx.AsyncClient,
) -> str:
    response = await client.get(
        f"{BASE_URL}/api/domains"
    )

    response.raise_for_status()

    data = response.json()

    if not data:
        raise RuntimeError(
            "Không có domain nào."
        )

    # Hỗ trợ cả:
    # ["domain1", "domain2"]
    #
    # hoặc:
    # [{"id": "domain1", ...}]
    first = data[0]

    if isinstance(first, str):
        return first

    if isinstance(first, dict):
        for key in (
            "id",
            "domain",
            "name",
        ):
            value = first.get(key)

            if value:
                return str(value)

    raise RuntimeError(
        "Không xác định được domain "
        f"từ response: {first}"
    )


async def send_request(
    client: httpx.AsyncClient,
    session_id: str,
    domain: str,
    request_number: int,
) -> tuple[int, str | None]:
    payload = {
        "query":
            "Kiểm tra rate limit.",
        "session_id":
            session_id,
        "domain":
            domain,
    }

    # Dùng stream để chỉ lấy HTTP status.
    # Không đọc toàn bộ SSE/AI response.
    async with client.stream(
        "POST",
        f"{BASE_URL}/api/chat",
        json=payload,
        headers={
            "X-Request-ID":
                f"rate-limit-test-"
                f"{request_number}",
        },
    ) as response:
        retry_after = (
            response.headers.get(
                "Retry-After"
            )
        )

        return (
            response.status_code,
            retry_after,
        )


async def main():
    timeout = httpx.Timeout(
        timeout=10.0,
        connect=5.0,
    )

    async with httpx.AsyncClient(
        timeout=timeout,
    ) as client:
        print(
            "Đang tạo anonymous session..."
        )

        session_id = await get_session(
            client
        )

        print(
            f"Session: {session_id}"
        )

        print(
            "Đang lấy domain hợp lệ..."
        )

        domain = await get_domain(
            client
        )

        print(
            f"Domain: {domain}"
        )

        print()
        print(
            "=" * 60
        )
        print(
            "RATE LIMIT TEST"
        )
        print(
            "=" * 60
        )

        status_counts = {}
        first_429 = None
        retry_after_value = None

        for request_number in range(
            1,
            TOTAL_REQUESTS + 1,
        ):
            try:
                (
                    status_code,
                    retry_after,
                ) = await send_request(
                    client,
                    session_id,
                    domain,
                    request_number,
                )

            except Exception as exc:
                print(
                    f"Request "
                    f"{request_number:02d}: "
                    f"ERROR "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                continue

            status_counts[
                status_code
            ] = (
                status_counts.get(
                    status_code,
                    0,
                )
                + 1
            )

            if (
                status_code == 429
                and first_429 is None
            ):
                first_429 = (
                    request_number
                )

                retry_after_value = (
                    retry_after
                )

            print(
                f"Request "
                f"{request_number:02d}: "
                f"HTTP {status_code}"
                + (
                    f" | Retry-After="
                    f"{retry_after}"
                    if retry_after
                    else ""
                )
            )

        print()
        print(
            "=" * 60
        )
        print(
            "RESULT"
        )
        print(
            "=" * 60
        )

        print(
            f"Total requests: "
            f"{TOTAL_REQUESTS}"
        )

        print(
            f"Status counts: "
            f"{status_counts}"
        )

        print(
            f"First 429 request: "
            f"{first_429}"
        )

        print(
            f"Retry-After: "
            f"{retry_after_value}"
        )

        if first_429 is not None:
            print()
            print(
                "PASS: Server đã trả "
                "HTTP 429 khi vượt "
                "rate limit."
            )

            sys.exit(0)

        print()
        print(
            "FAIL: Không nhận được "
            "HTTP 429."
        )

        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(
        main()
    )