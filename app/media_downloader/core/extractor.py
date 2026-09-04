from pathlib import Path

from app.config import get_settings

from ..platforms.base import BaseExtractor
from ..schemas.media import MediaInfo
from .cache import MediaCompositeCache, MediaFileCache, MediaRedisCache
from .concurrency import MediaConcurrencyManager, get_media_concurrency_manager
from .cookie_pool import mark_platform_cookie_failure, mark_platform_cookie_success
from .detector import detect_platform, normalize_share_url
from .errors import MediaRequestError, PlatformAuthRequiredError, PlatformParseError, UnsupportedPlatformError


MEDIA_PARSE_CACHE_NAMESPACE = "media-v6"


class MediaExtractorService:
    def __init__(
        self,
        extractors: list[BaseExtractor],
        cache: MediaFileCache | MediaRedisCache | MediaCompositeCache | None = None,
        concurrency: MediaConcurrencyManager | None = None,
    ) -> None:
        self.extractors = extractors
        self.cache = cache
        self.concurrency = concurrency

    async def parse(self, raw_url: str) -> MediaInfo:
        detection = detect_platform(raw_url)
        url = detection.normalized_url
        if self.cache:
            cached = self.cache.get(url)
            if cached:
                return cached
        if self.cache and self.concurrency:
            async with self.concurrency.parse_lock(self.cache.key_for(url)):
                cached = self.cache.get(url)
                if cached:
                    return cached
                return await self._extract_and_cache(url)
        return await self._extract_and_cache(url)

    async def _extract_and_cache(self, url: str) -> MediaInfo:
        extractor = self._get_extractor(url)
        try:
            if self.concurrency:
                async with self.concurrency.parse_slot(extractor.platform):
                    info = await extractor.extract(url)
            else:
                info = await extractor.extract(url)
        except (PlatformAuthRequiredError, MediaRequestError):
            mark_platform_cookie_failure(extractor.platform)
            raise
        else:
            mark_platform_cookie_success(extractor.platform)
        if self.cache:
            self.cache.set(url, info)
        return info

    def parse_id_for(self, raw_url: str) -> str:
        url = normalize_share_url(raw_url)
        if self.cache:
            return self.cache.key_for(url)
        return MediaFileCache(Path("."), ttl_seconds=0, namespace=MEDIA_PARSE_CACHE_NAMESPACE).key_for(url)

    def get_cached_parse(self, parse_id: str) -> MediaInfo:
        if not self.cache:
            raise PlatformParseError("PARSE_RESULT_EXPIRED")
        cached = self.cache.get_by_key(parse_id)
        if not cached:
            raise PlatformParseError("PARSE_RESULT_EXPIRED")
        return cached

    def _get_extractor(self, url: str) -> BaseExtractor:
        for extractor in self.extractors:
            if extractor.match(url):
                return extractor
        raise UnsupportedPlatformError("UNSUPPORTED_PLATFORM")


def build_media_extractor_service(storage_root: Path | None = None) -> MediaExtractorService:
    from ..platforms.douyin import DouyinExtractor
    from ..platforms.kuaishou import KuaishouExtractor
    from ..platforms.xiaohongshu import XHSExtractor

    settings = get_settings()
    root = storage_root or settings.storage_path
    file_cache = MediaFileCache(
        root / "media" / "cache",
        ttl_seconds=settings.MEDIA_CACHE_TTL_SECONDS,
        namespace=MEDIA_PARSE_CACHE_NAMESPACE,
    )
    return MediaExtractorService(
        [DouyinExtractor(), XHSExtractor(), KuaishouExtractor()],
        cache=file_cache,
        concurrency=get_media_concurrency_manager(),
    )
