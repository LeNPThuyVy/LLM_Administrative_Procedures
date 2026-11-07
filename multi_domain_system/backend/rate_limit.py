import os
import time
from collections import defaultdict, deque


DEFAULT_LIMIT_PER_MINUTE = 60
WINDOW_SECONDS = 60.0
MAX_TRACKED_CLIENTS = 10000


def _limit_per_minute() -> int:
    """0 tắt giới hạn, dùng khi chạy benchmark tải."""
    raw = os.getenv("CHAT_RATE_LIMIT_PER_MINUTE", "").strip()
    return int(raw) if raw else DEFAULT_LIMIT_PER_MINUTE


class ChatRateLimiter:
    """
    Giới hạn số câu hỏi theo cửa sổ trượt cho mỗi IP.

    Khóa theo IP chứ không theo cookie, vì client có thể tự đổi cookie.
    Bộ đếm nằm trong tiến trình, nên mỗi worker có giới hạn riêng.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, client_key: str) -> bool:
        limit = _limit_per_minute()
        if limit <= 0:
            return True

        now = self._clock()
        hits = self._hits[client_key]

        while hits and now - hits[0] >= WINDOW_SECONDS:
            hits.popleft()

        if len(hits) >= limit:
            return False

        hits.append(now)

        if len(self._hits) > MAX_TRACKED_CLIENTS:
            self._drop_idle_clients(now)

        return True

    def reset(self) -> None:
        self._hits.clear()

    def _drop_idle_clients(self, now: float) -> None:
        idle = [
            key
            for key, hits in self._hits.items()
            if not hits or now - hits[-1] >= WINDOW_SECONDS
        ]
        for key in idle:
            del self._hits[key]


chat_rate_limiter = ChatRateLimiter()
