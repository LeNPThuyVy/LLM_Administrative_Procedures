import argparse
import asyncio
import statistics
import time

import httpx


async def worker(
    client: httpx.AsyncClient,
    url: str,
    request_id: int,
    semaphore: asyncio.Semaphore,
):
    async with semaphore:
        started = time.perf_counter()

        try:
            response = await client.get(
                url,
                headers={
                    "X-Request-ID":
                        f"load-test-{request_id}"
                },
            )

            latency_ms = (
                time.perf_counter()
                - started
            ) * 1000

            return {
                "status_code":
                    response.status_code,
                "latency_ms":
                    latency_ms,
                "error":
                    None,
            }

        except Exception as exc:
            latency_ms = (
                time.perf_counter()
                - started
            ) * 1000

            return {
                "status_code":
                    None,
                "latency_ms":
                    latency_ms,
                "error":
                    type(exc).__name__,
            }


def percentile(
    values: list[float],
    percentile_value: float,
) -> float:
    if not values:
        return 0.0

    sorted_values = sorted(values)

    index = int(
        round(
            (
                percentile_value / 100
            )
            * (
                len(sorted_values) - 1
            )
        )
    )

    return sorted_values[index]


async def run_load_test(
    url: str,
    total_requests: int,
    concurrency: int,
):
    semaphore = asyncio.Semaphore(
        concurrency
    )

    timeout = httpx.Timeout(
        timeout=30.0,
        connect=5.0,
    )

    limits = httpx.Limits(
        max_connections=concurrency,
        max_keepalive_connections=(
            concurrency
        ),
    )

    started = time.perf_counter()

    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
    ) as client:
        tasks = [
            worker(
                client,
                url,
                request_id,
                semaphore,
            )
            for request_id
            in range(
                1,
                total_requests + 1,
            )
        ]

        results = await asyncio.gather(
            *tasks
        )

    total_time = (
        time.perf_counter()
        - started
    )

    latencies = [
        item["latency_ms"]
        for item in results
    ]

    success_count = sum(
        1
        for item in results
        if item["status_code"] == 200
    )

    rate_limited_count = sum(
        1
        for item in results
        if item["status_code"] == 429
    )

    server_error_count = sum(
        1
        for item in results
        if (
            item["status_code"] is not None
            and item["status_code"] >= 500
        )
    )

    network_error_count = sum(
        1
        for item in results
        if item["error"] is not None
    )

    error_count = (
        len(results)
        - success_count
    )

    error_rate = (
        error_count
        / len(results)
        * 100
        if results
        else 0.0
    )

    requests_per_second = (
        len(results)
        / total_time
        if total_time > 0
        else 0.0
    )

    print()
    print("=" * 60)
    print("LOAD TEST RESULT")
    print("=" * 60)

    print(
        f"URL: {url}"
    )

    print(
        f"Total requests: "
        f"{len(results)}"
    )

    print(
        f"Concurrency: "
        f"{concurrency}"
    )

    print(
        f"Success 200: "
        f"{success_count}"
    )

    print(
        f"Rate limited 429: "
        f"{rate_limited_count}"
    )

    print(
        f"Server errors 5xx: "
        f"{server_error_count}"
    )

    print(
        f"Network errors: "
        f"{network_error_count}"
    )

    print(
        f"Error rate: "
        f"{error_rate:.2f}%"
    )

    print(
        f"p50 latency: "
        f"{percentile(latencies, 50):.2f} ms"
    )

    print(
        f"p95 latency: "
        f"{percentile(latencies, 95):.2f} ms"
    )

    print(
        f"Average latency: "
        f"{statistics.mean(latencies):.2f} ms"
    )

    print(
        f"Total time: "
        f"{total_time:.2f} s"
    )

    print(
        f"Throughput: "
        f"{requests_per_second:.2f} req/s"
    )
    error_types = {}

    for item in results:
        if item["error"]:
            error_types[item["error"]] = (
                error_types.get(
                    item["error"],
                    0,
                )
                + 1
            )

    if error_types:
        print(
            f"Network error types: "
            f"{error_types}"
        )
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Simple async load test "
            "for Person C evaluation."
        )
    )

    parser.add_argument(
        "--url",
        default=(
            "http://127.0.0.1:8000/health"
        ),
    )

    parser.add_argument(
        "--requests",
        type=int,
        default=50,
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
    )

    args = parser.parse_args()

    asyncio.run(
        run_load_test(
            url=args.url,
            total_requests=args.requests,
            concurrency=args.concurrency,
        )
    )


if __name__ == "__main__":
    main()