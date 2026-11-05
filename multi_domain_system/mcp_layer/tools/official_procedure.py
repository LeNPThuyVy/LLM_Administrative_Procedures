import os
from typing import Any
from urllib.parse import quote_plus

import httpx


OFFICIAL_SEARCH_URL = (
    "https://vpcp.dichvucong.gov.vn/"
    "p/home/dvc-tthc-thu-tuc-hanh-chinh.html"
)


MOCK_PROCEDURES = {
    "đăng ký thường trú": {
        "title": "Đăng ký thường trú",
        "official_url": (
            "https://vpcp.dichvucong.gov.vn/"
            "p/home/dvc-tthc-thu-tuc-hanh-chinh-chi-tiet.html"
            "?ma_thu_tuc=6007"
        ),
        "source": "dichvucong.gov.vn",
    },
    "xác nhận tình trạng hôn nhân": {
        "title": "Xác nhận tình trạng hôn nhân",
        "official_url": "https://dichvucong.gov.vn/",
        "source": "dichvucong.gov.vn",
    },
}


def _is_mock_enabled() -> bool:
    return os.getenv("MCP_MOCK", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _mock_lookup(name: str) -> dict[str, Any]:
    normalized = name.strip().lower()

    for key, procedure in MOCK_PROCEDURES.items():
        if key in normalized or normalized in key:
            return {
                "success": True,
                "mock": True,
                "official": True,
                "query": name,
                "result": procedure,
            }

    return {
        "success": False,
        "mock": True,
        "official": True,
        "query": name,
        "error": f"No mock procedure found for: {name}",
    }


def lookup_official_procedure_data(name: str) -> dict[str, Any]:
    """
    Tra cứu thủ tục trên nguồn Cổng Dịch vụ công Quốc gia.

    Nếu MCP_MOCK=1 thì dùng dữ liệu mock để test không cần mạng.

    Live mode chỉ kiểm tra khả năng truy cập trang tìm kiếm chính thức.
    Không giả định API nội bộ không được công bố.
    """
    if not name or not name.strip():
        return {
            "success": False,
            "official": True,
            "error": "name is required",
        }

    if _is_mock_enabled():
        return _mock_lookup(name)

    try:
        params = {
            "tu_khoa": name.strip(),
        }

        with httpx.Client(
            timeout=5.0,
            follow_redirects=True,
            headers={
                "User-Agent": "LLM-Administrative-Procedures-MCP/1.0",
            },
        ) as client:
            response = client.get(
                OFFICIAL_SEARCH_URL,
                params=params,
            )
            response.raise_for_status()

        return {
            "success": True,
            "mock": False,
            "official": True,
            "query": name,
            "search_url": str(response.url),
            "status_code": response.status_code,
            "note": (
                "Official portal is reachable. "
                "No undocumented internal API is assumed."
            ),
        }

    except httpx.HTTPError as exc:
        return {
            "success": False,
            "mock": False,
            "official": True,
            "query": name,
            "error": f"Official portal request failed: {exc}",
        }