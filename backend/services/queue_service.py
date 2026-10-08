import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager


class QueueFullError(RuntimeError):
    """Raised when the waiting queue reached its configured limit."""


class QueueTimeoutError(RuntimeError):
    """Raised when a request waited too long for an execution slot."""


class QueueManager:
    def __init__(
        self,
        max_concurrency: int = 3,
        max_queue_size: int = 12,
        queue_timeout: float = 30.0,
    ):
        self.max_concurrency = max_concurrency
        self.max_queue_size = max_queue_size
        self.queue_timeout = queue_timeout

        self.semaphore = asyncio.Semaphore(max_concurrency)

        self.session_locks: dict[str, asyncio.Lock] = {}
        self._session_users = defaultdict(int)
        self._session_guard = asyncio.Lock()

        self._waiting = 0
        self._queue_guard = asyncio.Lock()

    @property
    def waiting_count(self) -> int:
        return self._waiting

    async def can_accept(self) -> bool:
        async with self._queue_guard:
            return self._waiting < self.max_queue_size

    async def acquire_slot(self):
        async with self._queue_guard:
            if self._waiting >= self.max_queue_size:
                raise QueueFullError(
                    "Server is busy. Please try again later."
                )

            self._waiting += 1

        try:
            try:
                await asyncio.wait_for(
                    self.semaphore.acquire(),
                    timeout=self.queue_timeout,
                )
            except asyncio.TimeoutError as exc:
                raise QueueTimeoutError(
                    "Timed out while waiting for an AI execution slot."
                ) from exc
        finally:
            async with self._queue_guard:
                self._waiting = max(0, self._waiting - 1)

    def release_slot(self):
        self.semaphore.release()

    @asynccontextmanager
    async def execution_slot(self):
        await self.acquire_slot()

        try:
            yield
        finally:
            self.release_slot()

    async def _get_or_create_session_lock(
        self,
        session_id: str,
    ) -> asyncio.Lock:
        async with self._session_guard:
            lock = self.session_locks.get(session_id)

            if lock is None:
                lock = asyncio.Lock()
                self.session_locks[session_id] = lock

            self._session_users[session_id] += 1

            return lock

    async def _release_session_reference(
        self,
        session_id: str,
        lock: asyncio.Lock,
    ):
        async with self._session_guard:
            self._session_users[session_id] -= 1

            if self._session_users[session_id] <= 0:
                self._session_users.pop(session_id, None)

                current_lock = self.session_locks.get(session_id)

                if (
                    current_lock is lock
                    and not lock.locked()
                ):
                    self.session_locks.pop(
                        session_id,
                        None,
                    )

    @asynccontextmanager
    async def session_scope(
        self,
        session_id: str,
    ):
        lock = await self._get_or_create_session_lock(
            session_id
        )

        try:
            async with lock:
                yield
        finally:
            await self._release_session_reference(
                session_id,
                lock,
            )

    def classify_request(self, query: str) -> str:
        query_lower = query.lower()

        tool_keywords = [
            "tra cứu",
            "tìm kiếm",
            "thời tiết",
            "realtime",
            "api",
        ]

        reasoning_keywords = [
            "so sánh",
            "phân tích",
            "giải thích",
            "tại sao",
            "các bước",
        ]

        if any(
            keyword in query_lower
            for keyword in tool_keywords
        ):
            return "tool"

        if any(
            keyword in query_lower
            for keyword in reasoning_keywords
        ):
            return "multi_step"

        return "simple"


queue_manager = QueueManager(
    max_concurrency=3,
    max_queue_size=12,
    queue_timeout=30.0,
)