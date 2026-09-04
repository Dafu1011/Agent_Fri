from collections.abc import Callable
from typing import Any

import httpx
from langchain_core.tools import tool

from app.config import settings

SearchResult = dict[str, str]
WeatherResult = dict[str, str]
ClientFactory = Callable[..., Any]

OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_WEATHER_CODES = {
    0: "晴朗",
    1: "主要晴朗",
    2: "局部多云",
    3: "阴天",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中等毛毛雨",
    55: "强毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "小阵雨",
    81: "中等阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴强冰雹",
}
LOCATION_ALIASES = {
    "北京": "Beijing",
    "北京市": "Beijing",
    "上海": "Shanghai",
    "上海市": "Shanghai",
    "广州": "Guangzhou",
    "广州市": "Guangzhou",
    "深圳": "Shenzhen",
    "深圳市": "Shenzhen",
    "杭州": "Hangzhou",
    "杭州市": "Hangzhou",
    "南京": "Nanjing",
    "南京市": "Nanjing",
    "成都": "Chengdu",
    "成都市": "Chengdu",
    "重庆": "Chongqing",
    "重庆市": "Chongqing",
    "武汉": "Wuhan",
    "武汉市": "Wuhan",
    "西安": "Xi'an",
    "西安市": "Xi'an",
    "长春": "Changchun",
    "长春市": "Changchun",
    "吉林长春": "Changchun",
    "吉林省长春": "Changchun",
    "吉林长春市": "Changchun",
    "吉林省长春市": "Changchun",
}


async def search_searxng(
    base_url: str,
    query: str,
    *,
    max_results: int = 5,
    language: str = "auto",
    safesearch: int = 1,
    client_factory: ClientFactory = httpx.AsyncClient,
) -> list[SearchResult]:
    search_url = f"{base_url.rstrip('/')}/search"
    params = {
        "q": query,
        "format": "json",
        "language": language,
        "safesearch": safesearch,
    }

    try:
        async with client_factory(timeout=10.0) as client:
            response = await client.get(
                search_url,
                params=params,
                headers={"Accept": "application/json"},
            )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return [
            {
                "title": "SearXNG search failed",
                "url": base_url,
                "snippet": str(exc),
                "source": "searxng",
            }
        ]

    results = payload.get("results", [])
    if not isinstance(results, list):
        return []

    normalized: list[SearchResult] = []
    for item in results[:max_results]:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "snippet": str(item.get("content") or ""),
                "source": str(item.get("engine") or "searxng"),
            }
        )
    return normalized


def _format_unit_value(value: Any, unit: str) -> str:
    return f"{value}{unit}" if value is not None else ""


def _weather_description(code: Any) -> str:
    try:
        normalized_code = int(code)
    except (TypeError, ValueError):
        return ""
    return OPEN_METEO_WEATHER_CODES.get(normalized_code, f"天气代码 {normalized_code}")


def _location_candidates(location: str) -> list[str]:
    normalized = location.strip()
    candidates = [normalized]
    alias = LOCATION_ALIASES.get(normalized)
    if alias:
        candidates.append(alias)
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


async def get_open_meteo_weather(
    location: str,
    *,
    client_factory: ClientFactory = httpx.AsyncClient,
) -> WeatherResult:
    try:
        async with client_factory(timeout=10.0) as client:
            matches = []
            for candidate in _location_candidates(location):
                geocoding_response = await client.get(
                    OPEN_METEO_GEOCODING_URL,
                    params={
                        "name": candidate,
                        "count": 3,
                        "language": "zh",
                        "format": "json",
                    },
                )
                geocoding_response.raise_for_status()
                geocoding_payload = geocoding_response.json()
                matches = geocoding_payload.get("results", [])
                if matches:
                    break
            if not matches:
                return {
                    "error": "Location not found",
                    "location": location,
                    "source": "Open-Meteo",
                }

            place = matches[0]
            forecast_response = await client.get(
                OPEN_METEO_FORECAST_URL,
                params={
                    "latitude": place.get("latitude"),
                    "longitude": place.get("longitude"),
                    "current": (
                        "temperature_2m,relative_humidity_2m,"
                        "apparent_temperature,precipitation,rain,"
                        "weather_code,wind_speed_10m"
                    ),
                    "timezone": "auto",
                    "forecast_days": 1,
                },
            )
        forecast_response.raise_for_status()
        forecast_payload = forecast_response.json()
    except Exception as exc:
        return {
            "error": str(exc),
            "location": location,
            "source": "Open-Meteo",
        }

    current = forecast_payload.get("current", {})
    units = forecast_payload.get("current_units", {})
    place_parts = [
        str(place.get("country") or ""),
        str(place.get("admin1") or ""),
        str(place.get("name") or location),
    ]

    return {
        "location": " ".join(part for part in place_parts if part),
        "time": str(current.get("time") or ""),
        "temperature": _format_unit_value(
            current.get("temperature_2m"),
            str(units.get("temperature_2m") or ""),
        ),
        "apparent_temperature": _format_unit_value(
            current.get("apparent_temperature"),
            str(units.get("apparent_temperature") or ""),
        ),
        "humidity": _format_unit_value(
            current.get("relative_humidity_2m"),
            str(units.get("relative_humidity_2m") or ""),
        ),
        "precipitation": _format_unit_value(
            current.get("precipitation"),
            str(units.get("precipitation") or ""),
        ),
        "rain": _format_unit_value(current.get("rain"), str(units.get("rain") or "")),
        "weather": _weather_description(current.get("weather_code")),
        "wind_speed": _format_unit_value(
            current.get("wind_speed_10m"),
            str(units.get("wind_speed_10m") or ""),
        ),
        "source": "Open-Meteo",
    }


def build_searxng_tool(base_url: str, max_results: int):
    @tool("web_search")
    async def web_search(query: str) -> list[SearchResult]:
        """Search the web for current information using the configured SearXNG instance."""
        return await search_searxng(
            base_url,
            query,
            max_results=max_results,
        )

    return web_search


def build_open_meteo_weather_tool():
    @tool("get_current_weather")
    async def get_current_weather(location: str) -> WeatherResult:
        """Get current weather, temperature, rain, wind, and humidity for a city or district using Open-Meteo."""
        return await get_open_meteo_weather(location)

    return get_current_weather


def build_web_tools() -> list[Any]:
    tools = [build_open_meteo_weather_tool()]
    provider = settings.web_search_provider.strip().lower()
    if provider != "searxng":
        return tools
    if not settings.searxng_base_url.strip():
        return tools
    tools.append(
        build_searxng_tool(
            settings.searxng_base_url.strip(),
            settings.web_search_max_results,
        )
    )
    return tools
