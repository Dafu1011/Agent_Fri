from datetime import datetime, timezone
from urllib.parse import unquote, urlparse
import json
import re

from app.config import get_settings

from ..core.cookie_pool import get_platform_cookie_identity
from ..core.errors import PlatformParseError
from ..schemas.media import MediaInfo
from ..utils.request import build_headers, fetch_text_response
from .base import BaseExtractor


class KuaishouExtractor(BaseExtractor):
    platform = "kuaishou"

    @classmethod
    def match(cls, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return host.endswith("kuaishou.com")

    @staticmethod
    def extract_photo_id(url: str) -> str:
        patterns = [r"[?&]photoId=([^&#]+)", r"/short-video/([^/?#]+)", r"/photo/([^/?#]+)"]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise PlatformParseError("无法从快手链接中提取作品 ID")

    @staticmethod
    def is_homepage_redirect(url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        return host.endswith("kuaishou.com") and path in {"", "/new-reco"}

    @classmethod
    def parse_photo_detail(cls, payload: dict[str, object]) -> MediaInfo:
        photo = payload.get("photo") or payload.get("photoDetail") or payload
        if not isinstance(photo, dict):
            raise PlatformParseError("快手作品详情格式不正确")
        user = photo.get("user") if isinstance(photo.get("user"), dict) else {}
        video_url = cls.video_url(photo)
        image_urls = cls.image_urls(
            photo.get("images")
            or photo.get("imageUrls")
            or photo.get("atlas")
            or photo.get("imageAtlas")
            or photo.get("imageAlbum")
            or photo.get("photoAtlas")
            or []
        )
        timestamp = photo.get("timestamp") or photo.get("createTime")
        create_value = None
        if isinstance(timestamp, (int, float)):
            create_value = datetime.fromtimestamp(timestamp / 1000 if timestamp > 10_000_000_000 else timestamp, tz=timezone.utc)
        duration = photo.get("duration")
        duration_seconds = int(duration // 1000) if isinstance(duration, int) else None
        if video_url:
            media_type = "video"
        elif image_urls:
            media_type = "images"
        else:
            raise PlatformParseError("未解析到快手媒体地址")
        return MediaInfo(
            platform="kuaishou",
            type=media_type,
            title=str(photo.get("caption") or photo.get("title") or ""),
            author=str(user.get("name") or user.get("nickname") or ""),
            cover=str(photo.get("coverUrl") or photo.get("cover") or ""),
            video_url=video_url,
            images=image_urls,
            duration=duration_seconds,
            create_time=create_value,
            raw={"source": "kuaishou"},
        )

    @classmethod
    def parse_page_html(cls, html: str) -> MediaInfo:
        for marker in ("window.__APOLLO_STATE__", "window.__INITIAL_STATE__"):
            payload_text = cls.extract_js_object(html, marker)
            if not payload_text:
                continue
            try:
                payload = json.loads(payload_text.replace("undefined", "null"))
            except json.JSONDecodeError:
                continue
            found = cls._find_photo(payload)
            if found:
                return cls.parse_photo_detail({"photo": cls._merge_author(payload, found)})

        decoded = cls.clean_url(unquote(html))
        found_urls = re.findall(r"https://[^\"'\\\s]+?\.(?:jpg|jpeg|png|webp|mp4)[^\"'\\\s]*", decoded)
        if found_urls:
            videos = [url for url in found_urls if ".mp4" in url]
            if videos:
                return MediaInfo(platform="kuaishou", type="video", video_url=videos[0])
        raise PlatformParseError("未在快手页面中找到作品媒体数据")

    @classmethod
    def video_url(cls, photo: dict[str, object]) -> str:
        for key in ("videoResource", "manifest", "coronaCropManifest"):
            url = cls.first_video_url(photo.get(key))
            if url:
                return url
        for key in ("photoUrl", "videoUrl", "src", "croppedPhotoUrl"):
            value = photo.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return cls.clean_url(value)
        return ""

    @classmethod
    def first_video_url(cls, value: object) -> str:
        urls = cls.video_urls(value)
        return urls[0] if urls else ""

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
        if isinstance(value.get("json"), (dict, list, str)):
            urls.extend(cls.video_urls(value.get("json")))
        for key in ("h264", "adaptationSet", "representation"):
            if key in value:
                urls.extend(cls.video_urls(value.get(key)))
        for key in ("url", "photoUrl", "videoUrl"):
            item = value.get(key)
            if isinstance(item, str) and item.startswith("http"):
                urls.append(cls.clean_url(item))
        for key in ("backupUrl", "backup_url", "backupUrls", "backup_urls"):
            if key in value:
                urls.extend(cls.video_urls(value.get(key)))
        for key in ("manifest", "videoResource"):
            if key in value:
                urls.extend(cls.video_urls(value.get(key)))
        return cls.unique_urls(urls)

    @classmethod
    def image_urls(cls, value: object) -> list[str]:
        if isinstance(value, str) and value.startswith("http"):
            return [cls.clean_url(value)]
        if isinstance(value, list):
            urls: list[str] = []
            for item in value:
                urls.extend(cls.image_urls(item))
            return cls.unique_urls(urls)
        if isinstance(value, dict):
            urls: list[str] = []
            for key in ("url", "urlDefault", "url_default", "imageUrl", "originUrl", "origin_url", "largeUrl", "photoUrl"):
                item = value.get(key)
                if isinstance(item, str) and item.startswith("http") and ".mp4" not in item:
                    urls.append(cls.clean_url(item))
            for key in ("images", "imageUrls", "list", "urls", "urlList", "atlas", "imageAtlas", "imageAlbum", "photoAtlas"):
                if key in value:
                    urls.extend(cls.image_urls(value.get(key)))
            return cls.unique_urls(urls)
        return []

    @classmethod
    def _find_photo(cls, value: object) -> dict[str, object] | None:
        if isinstance(value, dict):
            has_media = any(
                key in value
                for key in (
                    "photoUrl",
                    "videoUrl",
                    "images",
                    "imageUrls",
                    "atlas",
                    "imageAtlas",
                    "imageAlbum",
                    "photoAtlas",
                    "videoResource",
                    "manifest",
                )
            )
            has_text = any(key in value for key in ("caption", "title", "id"))
            if has_media and has_text:
                return value
            for item in value.values():
                found = cls._find_photo(item)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = cls._find_photo(item)
                if found:
                    return found
        return None

    @classmethod
    def _merge_author(cls, payload: dict[str, object], photo: dict[str, object]) -> dict[str, object]:
        if isinstance(photo.get("user"), dict):
            return photo
        author = cls._find_author_for_photo(payload, photo)
        if not author:
            return photo
        merged = dict(photo)
        merged["user"] = author
        return merged

    @classmethod
    def _find_author_for_photo(cls, payload: dict[str, object], photo: dict[str, object]) -> dict[str, object] | None:
        direct_author = photo.get("author") or photo.get("user")
        if isinstance(direct_author, dict):
            if isinstance(direct_author.get("id"), str):
                resolved = cls._lookup_apollo_ref(payload, direct_author["id"])
                if resolved:
                    return resolved
            if direct_author.get("name") or direct_author.get("nickname"):
                return direct_author

        photo_id = str(photo.get("id") or photo.get("photoId") or "")
        photo_ref_ids = {photo_id}
        if photo_id:
            photo_ref_ids.add(f"VisionVideoDetailPhoto:{photo_id}")

        query_author = cls._find_author_from_query(payload, payload, photo_ref_ids)
        if query_author:
            return query_author

        authors = cls._find_author_nodes(payload)
        return authors[0] if len(authors) == 1 else None

    @classmethod
    def _find_author_from_query(cls, root: object, value: object, photo_ref_ids: set[str]) -> dict[str, object] | None:
        if isinstance(value, dict):
            photo_ref = value.get("photo")
            author_ref = value.get("author")
            if cls._ref_matches(photo_ref, photo_ref_ids) and isinstance(author_ref, dict):
                author_id = author_ref.get("id")
                if isinstance(author_id, str):
                    return cls._lookup_apollo_ref(root, author_id)
            for item in value.values():
                found = cls._find_author_from_query(root, item, photo_ref_ids)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = cls._find_author_from_query(root, item, photo_ref_ids)
                if found:
                    return found
        return None

    @classmethod
    def _lookup_apollo_ref(cls, value: object, ref_id: str) -> dict[str, object] | None:
        if isinstance(value, dict):
            current = value.get(ref_id)
            if isinstance(current, dict):
                return current
            for item in value.values():
                found = cls._lookup_apollo_ref(item, ref_id)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = cls._lookup_apollo_ref(item, ref_id)
                if found:
                    return found
        return None

    @staticmethod
    def _ref_matches(value: object, ref_ids: set[str]) -> bool:
        if not isinstance(value, dict):
            return False
        ref_id = value.get("id")
        return isinstance(ref_id, str) and ref_id in ref_ids

    @classmethod
    def _find_author_nodes(cls, value: object) -> list[dict[str, object]]:
        if isinstance(value, dict):
            authors: list[dict[str, object]] = []
            typename = value.get("__typename") or value.get("typename")
            if (
                typename == "VisionVideoDetailAuthor"
                and isinstance(value.get("id"), str)
                and (value.get("name") or value.get("nickname"))
            ):
                authors.append(value)
            for item in value.values():
                authors.extend(cls._find_author_nodes(item))
            return authors
        if isinstance(value, list):
            authors: list[dict[str, object]] = []
            for item in value:
                authors.extend(cls._find_author_nodes(item))
            return authors
        return []

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
        response = await fetch_text_response(
            url,
            headers=build_headers(identity.cookie, identity.user_agent),
            timeout=settings.MEDIA_REQUEST_TIMEOUT_SECONDS,
        )
        if self.is_homepage_redirect(response.url):
            raise PlatformParseError("快手短链接已失效或被平台重定向到首页，请重新复制该作品的分享链接")
        return self.parse_page_html(response.text)
