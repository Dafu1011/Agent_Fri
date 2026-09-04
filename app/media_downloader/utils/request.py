from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from ..core.errors import MediaRequestError, MediaTimeoutError, PlatformAuthRequiredError


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class FetchedTextResponse:
    text: str
    url: str
    status_code: int


def build_headers(cookie: str = "", user_agent: str = "") -> dict[str, str]:
    headers = {
        "User-Agent": user_agent or DEFAULT_USER_AGENT,
        "Accept": "text/html,application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


async def fetch_text(url: str, *, headers: Mapping[str, str] | None = None, timeout: float = 20.0) -> str:
    response = await fetch_text_response(url, headers=headers, timeout=timeout)
    return response.text


async def fetch_text_response(url: str, *, headers: Mapping[str, str] | None = None, timeout: float = 20.0) -> FetchedTextResponse:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
            response = await client.get(url)
            if response.status_code in {401, 403}:
                raise PlatformAuthRequiredError("平台需要登录态或 Cookie 已失效")
            response.raise_for_status()
            return FetchedTextResponse(text=response.text, url=str(response.url), status_code=response.status_code)
    except httpx.TimeoutException as exc:
        raise MediaTimeoutError("请求第三方平台超时") from exc
    except httpx.HTTPStatusError as exc:
        raise MediaRequestError(f"第三方平台返回异常状态码: {exc.response.status_code}") from exc
