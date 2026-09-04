from datetime import datetime, timezone
from urllib.parse import urlencode, unquote, urlparse
import json
import re

from app.config import get_settings

from ..core.cookie_pool import get_platform_cookie_identity
from ..core.errors import PlatformAuthRequiredError, PlatformParseError
from ..schemas.media import MediaInfo
from ..utils.request import build_headers, fetch_text_response
from .base import BaseExtractor


DOUYIN_AUTH_MESSAGE = (
    "抖音返回了风控验证页，后端无法直接从 HTML 读取作品数据。"
    "请确认 cookie_manager/cookies.json 中存在 healthy 且未过期的 douyin Cookie；"
    "如该文件没有 user_agent，可继续用 MEDIA_DOUYIN_USER_AGENT 兜底。"
)


class DouyinExtractor(BaseExtractor):
    platform = "douyin"

    @classmethod
    def match(cls, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return host.endswith("douyin.com") or host.endswith("iesdouyin.com")

    @staticmethod
    def extract_aweme_id(url: str) -> str:
        patterns = [
            r"/video/(\d+)",
            r"/share/video/(\d+)",
            r"/note/(\d+)",
            r"/share/note/(\d+)",
            r"aweme_id=(\d+)",
            r"modal_id=(\d+)",
            r"[?&]vid=(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise PlatformParseError("无法从抖音链接中提取作品 ID")

    @staticmethod
    def first_url(value: object) -> str:
        if isinstance(value, dict):
            items = value.get("url_list")
            if isinstance(items, list) and items:
                return str(items[0])
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str):
            return value
        return ""

    @classmethod
    def urls_from_addr(cls, value: object) -> list[str]:
        if isinstance(value, dict):
            items = value.get("url_list")
            if isinstance(items, list):
                return [str(item) for item in items if item]
            url = value.get("url")
            if url:
                return [str(url)]
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if isinstance(value, str) and value:
            return [value]
        return []

    @staticmethod
    def normalize_media_url(url: str) -> str:
        return str(url or "").strip().replace("\\u002F", "/").replace("\\/", "/").replace("&amp;", "&")

    @classmethod
    def unique_urls(cls, urls: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for url in urls:
            cleaned = cls.normalize_media_url(url)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result

    @classmethod
    def select_image_urls(cls, detail: dict[str, object]) -> list[str]:
        image_items: list[object] = []
        for key in ("image_post_info", "imagePostInfo", "image_album", "imageAlbum"):
            container = detail.get(key)
            if isinstance(container, dict):
                for image_key in ("images", "image_list", "imageList"):
                    value = container.get(image_key)
                    if isinstance(value, list):
                        image_items.extend(value)
        for key in ("images", "image_list", "imageList"):
            value = detail.get(key)
            if isinstance(value, list):
                image_items.extend(value)

        urls: list[str] = []
        for item in image_items:
            selected = cls.best_image_url_from_item(item)
            if selected:
                urls.append(selected)
            else:
                urls.extend(cls.image_urls_from_item(item))
        return cls.unique_urls(urls)

    @classmethod
    def best_image_url_from_item(cls, value: object) -> str:
        if not isinstance(value, dict):
            urls = cls.image_urls_from_item(value)
            return urls[0] if urls else ""
        for key in ("display_image", "origin_image", "large_image", "image"):
            item = value.get(key)
            urls = [
                url
                for url in cls.image_urls_from_item(item)
                if not cls.is_watermark_url(url)
            ]
            if urls:
                return cls.preferred_image_url(urls)
        urls = [
            url
            for url in cls.image_urls_from_item(value)
            if not cls.is_watermark_url(url)
        ]
        return cls.preferred_image_url(urls) if urls else ""

    @classmethod
    def preferred_image_url(cls, urls: list[str]) -> str:
        unique = cls.unique_urls(urls)
        for url in unique:
            if ".webp" in url.lower() and "p3-" in urlparse(url).netloc.lower():
                return url
        for url in unique:
            if ".webp" in url.lower():
                return url
        return unique[0] if unique else ""

    @staticmethod
    def is_watermark_url(url: str) -> bool:
        lowered = url.lower()
        return "water" in lowered or "watermark" in lowered

    @classmethod
    def image_urls_from_item(cls, value: object) -> list[str]:
        if isinstance(value, str):
            cleaned = cls.normalize_media_url(value)
            if cleaned.startswith("http") and ".mp4" not in cleaned and "/video/" not in cleaned:
                return [cleaned]
            return []
        if isinstance(value, list):
            urls: list[str] = []
            for item in value:
                urls.extend(cls.image_urls_from_item(item))
            return cls.unique_urls(urls)
        if not isinstance(value, dict):
            return []

        urls: list[str] = []
        for key in ("display_image", "origin_image", "large_image", "image", "url_list", "download_url_list", "url"):
            item = value.get(key)
            if item:
                urls.extend(cls.image_urls_from_item(item))
        if urls:
            return cls.unique_urls(urls)

        for key, item in value.items():
            lowered = key.lower()
            if any(marker in lowered for marker in ("watermark", "avatar", "author", "music", "sticker")):
                continue
            urls.extend(cls.image_urls_from_item(item))
        return cls.unique_urls(urls)

    @staticmethod
    def normalize_no_watermark_url(url: str) -> str:
        value = str(url or "").strip()
        if not value:
            return ""
        value = value.replace("/playwm/", "/play/")
        value = value.replace("playwm", "play")
        value = re.sub(r"([?&])watermark=1(?=&|$)", r"\1watermark=0", value)
        return value

    @staticmethod
    def is_hevc_variant(value: object) -> bool:
        try:
            text = json.dumps(value, ensure_ascii=False).lower()
        except (TypeError, ValueError):
            text = str(value).lower()
        return any(marker in text for marker in ("h265", "hevc", "bytevc1", "h.265"))

    @classmethod
    def select_video_url(cls, video: dict[str, object]) -> str:
        h264_candidates: list[str] = []
        generic_candidates: list[str] = []
        hevc_fallback_candidates: list[str] = []
        bit_rates = video.get("bit_rate")
        if isinstance(bit_rates, list):
            def bitrate_value(item: object) -> int:
                return int(item.get("bit_rate") or 0) if isinstance(item, dict) else 0

            for item in sorted(bit_rates, key=bitrate_value, reverse=True):
                if not isinstance(item, dict):
                    continue
                h264_candidates.extend(cls.urls_from_addr(item.get("play_addr_h264")))
                target = hevc_fallback_candidates if cls.is_hevc_variant(item) else generic_candidates
                target.extend(cls.urls_from_addr(item.get("play_addr")))

        h264_candidates.extend(cls.urls_from_addr(video.get("play_addr_h264")))
        generic_candidates.extend(cls.urls_from_addr(video.get("play_addr")))
        hevc_fallback_candidates.extend(cls.urls_from_addr(video.get("play_addr_265")))
        hevc_fallback_candidates.extend(cls.urls_from_addr(video.get("play_addr_bytevc1")))

        for candidate in h264_candidates + generic_candidates + hevc_fallback_candidates:
            cleaned = cls.normalize_no_watermark_url(candidate)
            if cleaned:
                return cleaned
        return ""

    @classmethod
    def parse_aweme_detail(cls, payload: dict[str, object]) -> MediaInfo:
        detail = payload.get("aweme_detail") or payload.get("aweme") or payload
        if not isinstance(detail, dict):
            raise PlatformParseError("抖音作品详情格式不正确")
        video = detail.get("video") if isinstance(detail.get("video"), dict) else {}
        author = detail.get("author") if isinstance(detail.get("author"), dict) else {}
        video_url = cls.select_video_url(video) if isinstance(video, dict) else ""
        image_urls = cls.select_image_urls(detail)
        cover = cls.first_url(video.get("cover") if isinstance(video, dict) else None)
        create_time = detail.get("create_time")
        create_value = None
        if isinstance(create_time, (int, float)):
            create_value = datetime.fromtimestamp(create_time, tz=timezone.utc)
        duration = detail.get("duration")
        duration_seconds = int(duration // 1000) if isinstance(duration, int) else None
        if not video_url and not image_urls:
            raise PlatformParseError("未解析到抖音视频或图片地址")
        if image_urls:
            return MediaInfo(
                platform="douyin",
                type="images",
                title=str(detail.get("desc") or ""),
                author=str(author.get("nickname") or ""),
                cover=image_urls[0],
                images=image_urls,
                create_time=create_value,
                raw={"source": "douyin"},
            )
        return MediaInfo(
            platform="douyin",
            type="video",
            title=str(detail.get("desc") or ""),
            author=str(author.get("nickname") or ""),
            cover=cover,
            video_url=video_url,
            duration=duration_seconds,
            create_time=create_value,
            raw={"source": "douyin"},
        )

    @classmethod
    def parse_page_html(cls, html: str) -> MediaInfo:
        for payload_text in cls._iter_embedded_json(html):
            decoded_payload = unquote(payload_text)
            for candidate in (payload_text, decoded_payload):
                try:
                    payload = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
                found = cls._find_aweme_detail(payload)
                if found:
                    return cls.parse_aweme_detail({"aweme_detail": found})
        raise PlatformParseError("未在抖音页面中找到作品详情数据")

    @classmethod
    def _iter_embedded_json(cls, html: str) -> list[str]:
        payloads: list[str] = []
        render_match = re.search(r'<script[^>]+id=["\']RENDER_DATA["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
        if render_match:
            payloads.append(render_match.group(1).strip())

        router_match = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", html, re.DOTALL)
        if router_match:
            payloads.append(router_match.group(1).strip())

        return payloads

    @staticmethod
    def is_acrawler_challenge(html: str) -> bool:
        return "byted_acrawler" in html and ("__ac_signature" in html or "location.reload" in html)

    @classmethod
    def build_detail_api_url(cls, aweme_id: str) -> str:
        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": "1",
            "version_code": "290100",
            "version_name": "29.1.0",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "130.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "130.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "12",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "from_user_page": "1",
            "locate_query": "false",
            "need_time_list": "1",
            "pc_libra_divert": "Windows",
            "publish_video_strategy_type": "2",
            "round_trip_time": "0",
            "show_live_replay_strategy": "1",
            "time_list_query": "0",
            "whale_cut_token": "",
            "update_version_code": "170400",
            "msToken": "",
            "aweme_id": aweme_id,
        }
        return "https://www.douyin.com/aweme/v1/web/aweme/detail/?" + urlencode(params)

    @classmethod
    def parse_detail_api_payload(cls, text: str) -> MediaInfo:
        if not text.strip():
            raise PlatformAuthRequiredError("抖音接口未返回作品详情，Cookie 可能失效或请求被风控拦截，请更新 cookie_manager/cookies.json")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlatformParseError("抖音接口返回内容不是有效 JSON") from exc
        found = cls._find_aweme_detail(payload)
        if not found:
            status_msg = payload.get("status_msg") if isinstance(payload, dict) else ""
            if status_msg:
                raise PlatformAuthRequiredError(f"抖音接口未返回作品详情：{status_msg}")
            raise PlatformParseError("抖音接口未返回作品详情数据")
        return cls.parse_aweme_detail({"aweme_detail": found})

    async def extract_by_aweme_id(self, aweme_id: str, cookie: str, user_agent: str, timeout: float) -> MediaInfo:
        if not cookie:
            raise PlatformAuthRequiredError(DOUYIN_AUTH_MESSAGE)
        response = await fetch_text_response(
            self.build_detail_api_url(aweme_id),
            headers=build_headers(cookie, user_agent),
            timeout=timeout,
        )
        return self.parse_detail_api_payload(response.text)

    @classmethod
    def parse_page_html_or_auth_error(cls, html: str) -> MediaInfo:
        try:
            return cls.parse_page_html(html)
        except PlatformParseError as exc:
            if cls.is_acrawler_challenge(html):
                raise PlatformAuthRequiredError(DOUYIN_AUTH_MESSAGE) from exc
            raise

    async def extract_from_response(self, html: str, final_url: str, cookie: str, user_agent: str, timeout: float) -> MediaInfo:
        try:
            return self.parse_page_html(html)
        except PlatformParseError as page_error:
            try:
                aweme_id = self.extract_aweme_id(final_url)
            except PlatformParseError:
                if self.is_acrawler_challenge(html):
                    raise PlatformAuthRequiredError(DOUYIN_AUTH_MESSAGE) from page_error
                raise page_error
            return await self.extract_by_aweme_id(aweme_id, cookie, user_agent, timeout)

    async def extract(self, url: str) -> MediaInfo:
        settings = get_settings()
        identity = get_platform_cookie_identity(self.platform)
        response = await fetch_text_response(
            url,
            headers=build_headers(identity.cookie, identity.user_agent),
            timeout=settings.MEDIA_REQUEST_TIMEOUT_SECONDS,
        )
        return await self.extract_from_response(
            response.text,
            response.url,
            identity.cookie,
            identity.user_agent,
            settings.MEDIA_REQUEST_TIMEOUT_SECONDS,
        )

    @classmethod
    def _find_aweme_detail(cls, value: object) -> dict[str, object] | None:
        if isinstance(value, dict):
            if any(key in value for key in ("video", "image_post_info", "imagePostInfo", "images")) and (
                "desc" in value or "aweme_id" in value
            ):
                return value
            for key in ("aweme_detail", "awemeDetail", "aweme"):
                item = value.get(key)
                if isinstance(item, dict):
                    return item
            for item in value.values():
                found = cls._find_aweme_detail(item)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = cls._find_aweme_detail(item)
                if found:
                    return found
        return None
