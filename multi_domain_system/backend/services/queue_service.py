import asyncio
from collections import defaultdict
import my_config as cfg


class QueueManager:
    def __init__(self, max_concurrency: int = 3):
        self.session_locks = defaultdict(asyncio.Lock)
        self.semaphore = asyncio.Semaphore(max_concurrency)

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

        import my_config as cfg
        if getattr(cfg, "MULTI_INTENT_ENABLED", False):
            try:
                from rag.multi.detector import detect_sub_queries
                # We don't have domain and context here easily, but we can pass dummy values
                sub_queries, _ = detect_sub_queries(query, {}, cfg.DEFAULT_DOMAIN)
                if len(sub_queries) >= 2:
                    return "multi_step"
            except Exception:
                pass
                
        if any(keyword in query_lower for keyword in tool_keywords):
            return "tool"

        if any(keyword in query_lower for keyword in reasoning_keywords):
            return "multi_step"

        return "simple"


queue_manager = QueueManager(max_concurrency=max(4, getattr(cfg, "LLAMA_PARALLEL", 1) * 4))