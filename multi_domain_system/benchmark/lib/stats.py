"""Hàm thống kê nhỏ, không phụ thuộc thư viện ngoài."""
from __future__ import annotations


def percentile(values: list[float], p: float) -> float | None:
    """Percentile nội suy tuyến tính (p trong [0, 100])."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(values: list[float]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "mean": None, "min": None, "p50": None,
                "p90": None, "p95": None, "p99": None, "max": None}
    return {
        "n": len(vals),
        "mean": sum(vals) / len(vals),
        "min": min(vals),
        "p50": percentile(vals, 50),
        "p90": percentile(vals, 90),
        "p95": percentile(vals, 95),
        "p99": percentile(vals, 99),
        "max": max(vals),
    }


def linear_slope(xs: list[float], ys: list[float]) -> float | None:
    """Hệ số góc hồi quy tuyến tính (đơn vị y trên đơn vị x)."""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def fmt(x, nd: int = 2, unit: str = "") -> str:
    if x is None:
        return "–"
    if isinstance(x, bool):
        return "có" if x else "không"
    if isinstance(x, int):
        return f"{x}{unit}"
    return f"{x:.{nd}f}{unit}"


def rate(num: int, den: int) -> float | None:
    return None if den == 0 else num / den
