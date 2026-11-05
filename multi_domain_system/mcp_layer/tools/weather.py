import os
from typing import Any

import httpx


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


MOCK_WEATHER = {
    "ho chi minh city": {
        "city": "Ho Chi Minh City",
        "temperature_c": 30.0,
        "weather_code": 1,
        "source": "mock:open-meteo",
    },
    "da nang": {
        "city": "Da Nang",
        "temperature_c": 29.0,
        "weather_code": 2,
        "source": "mock:open-meteo",
    },
    "hanoi": {
        "city": "Hanoi",
        "temperature_c": 27.0,
        "weather_code": 3,
        "source": "mock:open-meteo",
    },
}


def _is_mock_enabled() -> bool:
    return os.getenv("MCP_MOCK", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _mock_weather(city: str) -> dict[str, Any]:
    key = city.strip().lower()

    result = MOCK_WEATHER.get(key)

    if result is None:
        return {
            "success": False,
            "mock": True,
            "official": False,
            "query": city,
            "error": f"No mock weather data for: {city}",
        }

    return {
        "success": True,
        "mock": True,
        "official": False,
        "query": city,
        "result": result,
    }


def get_weather_data(city: str) -> dict[str, Any]:
    """
    Lấy thời tiết hiện tại theo tên thành phố.

    Dùng Open-Meteo, không yêu cầu API key.
    Nếu MCP_MOCK=1 thì dùng dữ liệu mock để test offline.
    """
    if not city or not city.strip():
        return {
            "success": False,
            "official": False,
            "error": "city is required",
        }

    if _is_mock_enabled():
        return _mock_weather(city)

    try:
        with httpx.Client(
            timeout=5.0,
            follow_redirects=True,
        ) as client:
            geo_response = client.get(
                GEOCODING_URL,
                params={
                    "name": city.strip(),
                    "count": 1,
                    "language": "en",
                    "format": "json",
                },
            )
            geo_response.raise_for_status()
            geo_data = geo_response.json()

            results = geo_data.get("results") or []

            if not results:
                return {
                    "success": False,
                    "mock": False,
                    "official": False,
                    "query": city,
                    "error": f"City not found: {city}",
                }

            location = results[0]

            latitude = location["latitude"]
            longitude = location["longitude"]

            weather_response = client.get(
                WEATHER_URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "temperature_2m,weather_code",
                    "timezone": "auto",
                },
            )
            weather_response.raise_for_status()

            weather_data = weather_response.json()
            current = weather_data.get("current") or {}

        return {
            "success": True,
            "mock": False,
            "official": False,
            "query": city,
            "result": {
                "city": location.get("name", city),
                "country": location.get("country", ""),
                "latitude": latitude,
                "longitude": longitude,
                "temperature_c": current.get("temperature_2m"),
                "weather_code": current.get("weather_code"),
                "source": "open-meteo",
            },
        }

    except httpx.HTTPError as exc:
        return {
            "success": False,
            "mock": False,
            "official": False,
            "query": city,
            "error": f"Weather request failed: {exc}",
        }