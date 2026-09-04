from __future__ import annotations

from ..schemas.media import MediaInfo
from ..utils.request import build_headers
from .cookie_pool import get_platform_cookie_identity


PLATFORM_RESOURCE_REFERERS = {
    "douyin": "https://www.douyin.com/",
    "xiaohongshu": "https://www.xiaohongshu.com/",
    "kuaishou": "https://www.kuaishou.com/",
}


def build_media_resource_headers(info: MediaInfo, *, range_header: str = "") -> dict[str, str]:
    identity = get_platform_cookie_identity(info.platform)
    referer = PLATFORM_RESOURCE_REFERERS.get(info.platform, "")
    headers = build_headers(identity.cookie, identity.user_agent)
    headers["Accept"] = "video/webm,video/mp4,video/*;q=0.9,image/*;q=0.8,*/*;q=0.7"
    if referer:
        headers["Referer"] = referer
        headers["Origin"] = referer.rstrip("/")
    if range_header:
        headers["Range"] = range_header
    return headers
