from urllib.parse import urlparse
import re

from ..schemas.media import PlatformDetection
from .errors import InvalidMediaUrlError, UnsupportedPlatformError


URL_PATTERN = re.compile(r"https?://[^\s\"'<>，。)）]+", re.IGNORECASE)

PLATFORM_HOSTS: dict[str, tuple[str, ...]] = {
    "douyin": ("douyin.com", "iesdouyin.com"),
    "xiaohongshu": ("xiaohongshu.com", "xhslink.com", "xhslink.cn"),
    "kuaishou": ("kuaishou.com",),
}


def normalize_share_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise InvalidMediaUrlError("请输入分享链接")
    match = URL_PATTERN.search(value)
    if match:
        return match.group(0).rstrip(").,，。")
    raise InvalidMediaUrlError("未找到有效的 http 或 https 分享链接")


def detect_platform(raw: str) -> PlatformDetection:
    url = normalize_share_url(raw)
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not parsed.scheme or not host:
        raise InvalidMediaUrlError("分享链接格式不正确")
    for platform, suffixes in PLATFORM_HOSTS.items():
        if any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes):
            return PlatformDetection(platform=platform, normalized_url=url)
    raise UnsupportedPlatformError("暂不支持该平台")
