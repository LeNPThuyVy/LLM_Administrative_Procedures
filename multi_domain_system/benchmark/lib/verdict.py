"""Gói kết quả của một suite + so sánh với ngưỡng (SLO)."""
from __future__ import annotations


def verdict(key: str, label: str, value, op: str, target, unit: str = "",
            note: str = "") -> dict:
    """op: '<=' (thấp hơn là tốt) hoặc '>=' (cao hơn là tốt)."""
    if value is None or target is None:
        status = "SKIP"
    elif op == "<=":
        status = "PASS" if value <= target else "FAIL"
    else:
        status = "PASS" if value >= target else "FAIL"
    return {"key": key, "label": label, "value": value, "op": op,
            "target": target, "unit": unit, "status": status, "note": note}


def new_result(name: str, title: str) -> dict:
    return {"name": name, "title": title, "verdicts": [], "tables": [],
            "notes": [], "raw": {}}


def table(title: str, headers: list[str], rows: list[list]) -> dict:
    return {"title": title, "headers": headers, "rows": rows}
