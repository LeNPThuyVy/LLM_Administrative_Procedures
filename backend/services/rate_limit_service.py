import asyncio
import math
import os
import time
from collections import deque


class RateLimitExceeded(RuntimeError):
    def __init__(
        self,
        scope: str,
        retry_after: int,
    ):
        self.scope = scope
        self.retry_after = retry_after

        super().__init__(
            f"Rate limit exceeded for {scope}. "
            f"Retry after {retry_after}s."
        )


class RateLimiter:
    def __init__(
        self,
        session_limit: int = 20,
        ip_limit: int = 60,
        window_seconds: int = 60,
    ):
        self.session_limit = session_limit
        self.ip_limit = ip_limit
        self.window_seconds = window_seconds

        self._hits: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    def _cleanup_bucket(
        self,
        bucket: deque[float],
        now: float,
    ) -> None:
        cutoff = now - self.window_seconds

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    async def check(
        self,
        session_id: str,
        ip_address: str,
    ) -> None:
        now = time.monotonic()

        checks = [
            (
                f"session:{session_id}",
                self.session_limit,
                "session",
            ),
            (
                f"ip:{ip_address}",
                self.ip_limit,
                "ip",
            ),
        ]

        async with self._lock:
            buckets = []

            for key, limit, scope in checks:
                bucket = self._hits.setdefault(
                    key,
                    deque(),
                )

                self._cleanup_bucket(
                    bucket,
                    now,
                )

                if len(bucket) >= limit:
                    oldest = bucket[0]

                    retry_after = max(
                        1,
                        math.ceil(
                            self.window_seconds
                            - (now - oldest)
                        ),
                    )

                    raise RateLimitExceeded(
                        scope=scope,
                        retry_after=retry_after,
                    )

                buckets.append(bucket)

            for bucket in buckets:
                bucket.append(now)

            empty_keys = [
                key
                for key, bucket in self._hits.items()
                if not bucket
            ]

            for key in empty_keys:
                self._hits.pop(key, None)


rate_limiter = RateLimiter(
    session_limit=int(
        os.getenv(
            "RATE_LIMIT_SESSION_REQUESTS",
            "20",
        )
    ),
    ip_limit=int(
        os.getenv(
            "RATE_LIMIT_IP_REQUESTS",
            "60",
        )
    ),
    window_seconds=int(
        os.getenv(
            "RATE_LIMIT_WINDOW_SECONDS",
            "60",
        )
    ),
)