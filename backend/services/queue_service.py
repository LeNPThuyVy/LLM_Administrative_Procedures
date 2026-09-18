import asyncio
from collections import defaultdict


class QueueManager:
    def __init__(self, max_concurrency: int = 3):
        self.session_locks = defaultdict(asyncio.Lock)
        self.semaphore = asyncio.Semaphore(1)

    def get_session_lock(self, session_id: str):
        return self.session_locks[session_id]

    def classify_request(self, query: str) -> str:
        query_lower = query.lower()

        tool_keywords = [
            "tra cứu",
            "tìm kiếm",
            "thời tiết",
            "realtime",
            "api"
        ]

        reasoning_keywords = [
            "so sánh",
            "phân tích",
            "giải thích",
            "tại sao",
            "các bước"
        ]

        if any(keyword in query_lower for keyword in tool_keywords):
            return "tool"

        if any(keyword in query_lower for keyword in reasoning_keywords):
            return "multi_step"

        return "simple"


queue_manager = QueueManager(max_concurrency=3)