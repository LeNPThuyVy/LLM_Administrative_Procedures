from __future__ import annotations

from typing import Any


def new_result(suite_name: str, title: str) -> dict:
    """Khởi tạo container kết quả cho một suite benchmark."""
    return {
        "name": suite_name,
        "title": title,
        "verdicts": [],
        "tables": [],
        "notes": [],
        "raw": {},
    }


def table(title: str, headers: list[str], rows: list[list[Any]]) -> dict:
    """Tạo metadata bảng kết quả để render ra markdown / json."""
    return {
        "title": title,
        "headers": headers,
        "rows": rows,
    }


def verdict(
    key: str,
    label: str,
    value: Any,
    op: str,
    target: Any,
    unit: str = "",
    note: str = "",
) -> dict:
    """
    Đánh giá một chỉ số so với ngưỡng (SLO).
    op: '<=', '>=', '==', '<', '>'
    """
    if value is None:
        status = "SKIP"
    else:
        try:
            val_num = float(value)
            tgt_num = float(target)
            if op == "<=":
                status = "PASS" if val_num <= tgt_num else "FAIL"
            elif op == ">=":
                status = "PASS" if val_num >= tgt_num else "FAIL"
            elif op == "==":
                status = "PASS" if val_num == tgt_num else "FAIL"
            elif op == "<":
                status = "PASS" if val_num < tgt_num else "FAIL"
            elif op == ">":
                status = "PASS" if val_num > tgt_num else "FAIL"
            else:
                status = "PASS" if value == target else "FAIL"
        except (ValueError, TypeError):
            if op == "==":
                status = "PASS" if str(value) == str(target) else "FAIL"
            else:
                status = "SKIP"

    return {
        "key": key,
        "label": label,
        "value": value,
        "op": op,
        "target": target,
        "unit": unit,
        "status": status,
        "note": note,
    }
