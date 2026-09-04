from datetime import datetime, timezone
from urllib.parse import unquote, urlparse
import json
import re

from app.config import get_settings

from ..core.cookie_pool import get_platform_cookie_identity
from ..core.errors import PlatformParseError
from ..schemas.media import MediaInfo
from ..utils.request import build_headers, fetch_text
from .base import BaseExtractor


class XHSExtractor(BaseExtractor):
    platform = "xiaohongshu"

    @classmethod
    def match(cls, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return host.endswith("xiaohongshu.com") or host.endswith("xhslink.com") or host.endswith("xhslink.cn")

    @staticmethod
    def extract_note_id(url: str) -> str:
        patterns = [r"/explore/([^/?#]+)", r"/discovery/item/([^/?#]+)", r"[?&]note_id=([^&#]+)"]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise PlatformParseError("无法从小红书链接中提取笔记 ID")

    @classmethod
    def image_url(cls, item: object) -> str:
        if isinstance(item, str) and item.startswith("http"):
            return cls.clean_url(item)
        if not isinstance(item, dict):
            return ""
        for key in ("url_default", "urlDefault", "url_pre", "urlPre", "url", "imageUrl"):
            value = item.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return cls.clean_url(value)
        for key in ("infoList", "info_list", "list"):
            nested = item.get(key)
            if isinstance(nested, list):
                for entry in nested:
                    url = cls.image_url(entry)
                    if url:
                        return url
        return ""

    @classmethod
    def video_url(cls, video: object) -> str:
        for url in cls.video_urls(video):
            return url
        return ""

    @classmethod
    def video_urls(cls, value: object) -> list[str]:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    return cls.video_urls(json.loads(stripped))
                except json.JSONDecodeError:
                    return []
            if stripped.startswith("http") and (".mp4" in stripped or "video" in stripped):
                return [cls.clean_url(stripped)]
            return []
        if isinstance(value, list):
            urls: list[str] = []
            for item in value:
                urls.extend(cls.video_urls(item))
            return urls
        if not isinstance(value, dict):
            return []

        urls: list[str] = []
        for key in ("h264", "h265", "av1", "stream"):
            if key in value:
                urls.extend(cls.video_urls(value.get(key)))
        for key in ("master_url", "masterUrl", "backup_url", "backupUrl", "url"):
            item = value.get(key)
            if isinstance(item, str) and item.startswith("http"):
                urls.append(cls.clean_url(item))
            elif isinstance(item, list):
                urls.extend(cls.video_urls(item))
        for key in ("backup_urls", "backupUrls", "media", "mediaV2", "video", "representation", "adaptationSet"):
            if key in value:
                urls.extend(cls.video_urls(value.get(key)))
        return cls.unique_urls(urls)

    @classmethod
    def parse_note_state(cls, payload: dict[str, object]) -> MediaInfo:
        note = cls.unwrap_note(payload)
        if not isinstance(note, dict):
            raise PlatformParseError("小红书笔记详情格式不正确")
        user = note.get("user") if isinstance(note.get("user"), dict) else {}
        image_items = note.get("image_list") or note.get("imageList") or note.get("images") or []
        images = [cls.image_url(item) for item in image_items] if isinstance(image_items, list) else []
        images = cls.unique_urls([url for url in images if url])
        video_url = cls.video_url(note.get("video"))
        timestamp = note.get("time") or note.get("create_time") or note.get("createTime")
        create_value = None
        if isinstance(timestamp, (int, float)):
            create_value = datetime.fromtimestamp(timestamp / 1000 if timestamp > 10_000_000_000 else timestamp, tz=timezone.utc)
        if video_url:
            media_type = "video"
        elif images:
            media_type = "images"
        else:
            raise PlatformParseError("未解析到小红书媒体地址")
        return MediaInfo(
            platform="xiaohongshu",
            type=media_type,
            title=str(note.get("title") or note.get("desc") or ""),
            author=str(user.get("nickname") or user.get("name") or ""),
            cover=images[0] if images else "",
            video_url=video_url,
            images=[] if video_url else images,
            create_time=create_value,
            raw={"source": "xiaohongshu"},
        )

    @classmethod
    def parse_page_html(cls, html: str) -> MediaInfo:
        for marker in ("window.__INITIAL_STATE__", "window.__INITIAL_STATE__="):
            payload_text = cls.extract_js_object(html, marker)
            if not payload_text:
                continue
            try:
                payload = json.loads(payload_text.replace("undefined", "null"))
            except json.JSONDecodeError:
                continue
            found = cls._find_note(payload)
            if found:
                return cls.parse_note_state({"note": found})

        decoded = cls.clean_url(unquote(html))
        found_urls = cls.extract_trusted_media_urls(decoded)
        if found_urls:
            videos = [url for url in found_urls if ".mp4" in url]
            images = [url for url in found_urls if ".mp4" not in url]
            if videos:
                return MediaInfo(platform="xiaohongshu", type="video", video_url=videos[0], cover=images[0] if images else "")
            return MediaInfo(platform="xiaohongshu", type="images", images=cls.unique_urls(images))
        raise PlatformParseError("未在小红书页面中找到笔记媒体数据")

    @classmethod
    def unwrap_note(cls, payload: dict[str, object]) -> dict[str, object] | object:
        note = payload.get("note") or payload.get("noteData") or payload
        if isinstance(note, dict) and "noteDetailMap" in note:
            found = cls._find_note(note.get("noteDetailMap"))
            if found:
                return found
        return note

    @classmethod
    def _find_note(cls, value: object) -> dict[str, object] | None:
        if isinstance(value, dict):
            if "note" in value and isinstance(value.get("note"), dict):
                found = cls._find_note(value.get("note"))
                if found:
                    return found
            has_media = any(key in value for key in ("image_list", "imageList", "images", "video"))
            has_text = any(key in value for key in ("title", "desc", "noteId"))
            if has_media and has_text:
                return value
            for item in value.values():
                found = cls._find_note(item)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = cls._find_note(item)
                if found:
                    return found
        return None

    @staticmethod
    def extract_js_object(html: str, marker: str) -> str:
        start = html.find(marker)
        if start < 0:
            return ""
        equals_at = html.find("=", start)
        object_start = html.find("{", equals_at if equals_at >= 0 else start)
        if object_start < 0:
            return ""
        depth = 0
        in_string = False
        escaped = False
        for index in range(object_start, len(html)):
            char = html[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return html[object_start : index + 1]
        return ""

    @staticmethod
    def clean_url(value: str) -> str:
        return value.replace("\\u002F", "/").replace("\\/", "/").replace("&amp;", "&")

    @classmethod
    def extract_trusted_media_urls(cls, html: str) -> list[str]:
        candidates = re.findall(r"https://[^\"'\\\s<>]+?(?:\.(?:jpg|jpeg|png|webp|mp4)[^\"'\\\s<>]*|!nd_[^\"'\\\s<>]*)", html)
        return cls.unique_urls([url for url in candidates if cls.is_trusted_media_url(url)])

    @staticmethod
    def is_trusted_media_url(url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return host.endswith(".xhscdn.com") or host.endswith(".xiaohongshu.com")

    @staticmethod
    def unique_urls(urls: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                result.append(url)
        return result

    async def extract(self, url: str) -> MediaInfo:
        settings = get_settings()
        identity = get_platform_cookie_identity(self.platform)
        html = await fetch_text(
            url,
            headers=build_headers(identity.cookie, identity.user_agent),
            timeout=settings.MEDIA_REQUEST_TIMEOUT_SECONDS,
        )
        return self.parse_page_html(html)
