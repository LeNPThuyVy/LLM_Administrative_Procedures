from __future__ import annotations

import logging
from collections import OrderedDict
from rag.mapper import AnswerResponse

logger = logging.getLogger(__name__)

_PIPELINE_ANSWER_CACHE: OrderedDict[tuple, AnswerResponse] = OrderedDict()
_MAX_ANSWER_CACHE_SIZE = 500


def get_cache_key(query: str, context: dict | None, domain: str | None, session_id: str | None = None) -> tuple:
    q_norm = (query or "").strip().lower()
    proc = ""
    if context:
        sc = context.get("structured_context") or {}
        if isinstance(sc, dict):
            proc = str(sc.get("procedure_name", "")).strip().lower()
    return (session_id or "global", q_norm, proc, domain or "default")


def get_cached_answer(cache_key: tuple) -> AnswerResponse | None:
    if cache_key in _PIPELINE_ANSWER_CACHE:
        _PIPELINE_ANSWER_CACHE.move_to_end(cache_key)
        return _PIPELINE_ANSWER_CACHE[cache_key]
    return None


def set_cached_answer(cache_key: tuple, response: AnswerResponse) -> None:
    if len(_PIPELINE_ANSWER_CACHE) >= _MAX_ANSWER_CACHE_SIZE:
        _PIPELINE_ANSWER_CACHE.popitem(last=False)
    _PIPELINE_ANSWER_CACHE[cache_key] = response

