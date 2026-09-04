from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import asyncio
import time

from app.config import settings

from .errors import MediaDownloaderError


class ConcurrencyLimitExceeded(MediaDownloaderError):
    status_code = 429


class MediaConcurrencyManager:
    def __init__(
        self,
        *,
        parse_lock_ttl_seconds: int = 30,
        parse_concurrency_limit: int = 5,
        platform_parse_concurrency_limits: dict[str, int] | None = None,
        preview_lock_ttl_seconds: int = 300,
        preview_concurrency_limit: int = 5,
    ) -> None:
        self.parse_lock_ttl_seconds = max(1, int(parse_lock_ttl_seconds))
        self.preview_lock_ttl_seconds = max(1, int(preview_lock_ttl_seconds))
        self._parse_slots = asyncio.BoundedSemaphore(max(1, int(parse_concurrency_limit)))
        self._platform_parse_slots = {
            platform: asyncio.BoundedSemaphore(max(1, int(limit)))
            for platform, limit in (platform_parse_concurrency_limits or {}).items()
        }
        self._preview_slots = asyncio.BoundedSemaphore(max(1, int(preview_concurrency_limit)))
        self._locks: dict[str, float] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def parse_lock(self, cache_key: str) -> AsyncIterator[None]:
        async with self._coalescing_lock(f"parse:{cache_key}", self.parse_lock_ttl_seconds):
            yield

    @asynccontextmanager
    async def preview_lock(self, parse_id: str) -> AsyncIterator[None]:
        async with self._coalescing_lock(f"preview:{parse_id}", self.preview_lock_ttl_seconds):
            yield

    @asynccontextmanager
    async def parse_slot(self, platform: str) -> AsyncIterator[None]:
        await self._acquire_with_short_wait(self._parse_slots)
        platform_slot = self._platform_parse_slots.get(platform)
        platform_acquired = False
        try:
            if platform_slot is not None:
                await self._acquire_with_short_wait(platform_slot)
                platform_acquired = True
            yield
        finally:
            if platform_slot is not None and platform_acquired:
                platform_slot.release()
            self._parse_slots.release()

    @asynccontextmanager
    async def preview_slot(self) -> AsyncIterator[None]:
        await self._acquire_with_short_wait(self._preview_slots)
        try:
            yield
        finally:
            self._preview_slots.release()

    async def _acquire_with_short_wait(self, semaphore: asyncio.BoundedSemaphore) -> None:
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=0.001)
        except asyncio.TimeoutError as exc:
            raise ConcurrencyLimitExceeded("服务器繁忙，请稍后重试") from exc

    @asynccontextmanager
    async def _coalescing_lock(self, key: str, ttl_seconds: int) -> AsyncIterator[None]:
        deadline = time.monotonic() + ttl_seconds
        while True:
            if await self._try_acquire_lock(key, ttl_seconds):
                break
            if time.monotonic() >= deadline:
                raise ConcurrencyLimitExceeded("同一媒体任务正在处理中，请稍后重试")
            await asyncio.sleep(0.05)
        try:
            yield
        finally:
            async with self._guard:
                self._locks.pop(key, None)

    async def _try_acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        now = time.monotonic()
        async with self._guard:
            expired = [item for item, expires_at in self._locks.items() if expires_at <= now]
            for item in expired:
                self._locks.pop(item, None)
            if key in self._locks:
                return False
            self._locks[key] = now + ttl_seconds
            return True


_media_concurrency_manager: MediaConcurrencyManager | None = None


def get_media_concurrency_manager() -> MediaConcurrencyManager:
    global _media_concurrency_manager
    if _media_concurrency_manager is None:
        _media_concurrency_manager = MediaConcurrencyManager(
            parse_lock_ttl_seconds=settings.media_parse_lock_ttl_seconds,
            parse_concurrency_limit=settings.media_parse_concurrency_limit,
            platform_parse_concurrency_limits={
                "douyin": settings.media_douyin_parse_concurrency_limit,
                "xiaohongshu": settings.media_xhs_parse_concurrency_limit,
                "kuaishou": settings.media_kuaishou_parse_concurrency_limit,
            },
            preview_lock_ttl_seconds=settings.media_preview_lock_ttl_seconds,
            preview_concurrency_limit=settings.media_preview_concurrency_limit,
        )
    return _media_concurrency_manager
