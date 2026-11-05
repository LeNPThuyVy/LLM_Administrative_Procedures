from __future__ import annotations

import math
from typing import Sequence


def percentile(data: Sequence[float], p: float) -> float | None:
    """Tính phân vị p (0..100) của dãy số."""
    if not data:
        return None
    s = sorted(data)
    k = (len(s) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(s[int(k)])
    d0 = s[int(f)] * (c - k)
    d1 = s[int(c)] * (k - f)
    return float(d0 + d1)


def rate(num: int | float, denom: int | float) -> float:
    """Tính tỷ lệ an toàn tránh chia cho 0."""
    return float(num) / float(denom) if denom else 0.0


def summarize(data: Sequence[float]) -> dict:
    """Tổng hợp thống kê mô tả (n, mean, p50, p90, p95, p99, max)."""
    if not data:
        return {
            "n": 0,
            "mean": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
        }
    clean = [float(x) for x in data if x is not None]
    if not clean:
        return {
            "n": 0,
            "mean": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
        }
    n = len(clean)
    mean_val = sum(clean) / n
    return {
        "n": n,
        "mean": mean_val,
        "p50": percentile(clean, 50) or 0.0,
        "p90": percentile(clean, 90) or 0.0,
        "p95": percentile(clean, 95) or 0.0,
        "p99": percentile(clean, 99) or 0.0,
        "max": max(clean),
    }
