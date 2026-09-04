from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
import asyncio
import mimetypes
import shutil
import time
import uuid

import httpx
from fastapi.responses import FileResponse

from ..schemas.media import MediaInfo
from .concurrency import MediaConcurrencyManager
from .errors import MediaDownloadError, MediaTimeoutError
from .headers import build_media_resource_headers


FetchPreviewToPath = Callable[[str, Path, int, Mapping[str, str]], Awaitable[str]]
TranscodePreview = Callable[[Path, Path], Awaitable[None]]
PREVIEW_CACHE_VERSION = "v3"
PREVIEW_URL_VERSION = "3"


class MediaPreviewStreamer:
    def __init__(
        self,
        storage_root: Path,
        *,
        fetcher: FetchPreviewToPath | None = None,
        transcoder: TranscodePreview | None = None,
        timeout_seconds: float = 120.0,
        max_preview_mb: int = 500,
        preview_cache_ttl_seconds: int = 86400,
        preview_cache_max_mb: int = 2048,
        concurrency: MediaConcurrencyManager | None = None,
    ) -> None:
        self.storage_root = storage_root
        self.fetcher = fetcher or self._fetch_to_path
        self.transcoder = transcoder
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_preview_mb * 1024 * 1024
        self.preview_cache_ttl_seconds = max(1, int(preview_cache_ttl_seconds))
        self.preview_cache_max_bytes = max(1, int(preview_cache_max_mb)) * 1024 * 1024
        self.concurrency = concurrency

    async def stream(self, info: MediaInfo, parse_id: str, range_header: str = "") -> FileResponse:
        url = info.video_url
        if not url:
            raise MediaDownloadError("没有可预览的视频地址")

        path = self.path_for(parse_id, url)
        if not path.exists() or path.stat().st_size <= 0:
            self.cleanup_preview_cache()
            if self.concurrency:
                async with self.concurrency.preview_lock(parse_id):
                    if not path.exists() or path.stat().st_size <= 0:
                        async with self.concurrency.preview_slot():
                            await self.materialize(url, path, info)
            else:
                await self.materialize(url, path, info)

        media_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
        return FileResponse(
            path,
            media_type=media_type,
            headers={
                "Accept-Ranges": "bytes",
                "Cache-Control": "private, max-age=300",
                "Content-Disposition": "inline",
            },
        )

    async def materialize(self, url: str, path: Path, info: MediaInfo) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        source_path = path.with_name(f"{path.stem}.{token}.source")
        transcoded_path = path.with_name(f"{path.stem}.{token}.browser.mp4")
        try:
            content_type = await self.fetcher(url, source_path, self.max_bytes, build_media_resource_headers(info))
            if not source_path.exists() or source_path.stat().st_size <= 0:
                raise MediaDownloadError("预览视频文件为空")
            if self.transcoder:
                try:
                    await self.transcoder(source_path, transcoded_path)
                except Exception as exc:
                    if self._is_browser_mp4(source_path, url, content_type):
                        source_path.replace(path)
                        return
                    raise MediaDownloadError(f"预览视频转码失败: {exc}") from exc
                if not transcoded_path.exists() or transcoded_path.stat().st_size <= 0:
                    raise MediaDownloadError("预览视频转码后文件为空")
                transcoded_path.replace(path)
            else:
                source_path.replace(path)
        except Exception:
            source_path.unlink(missing_ok=True)
            transcoded_path.unlink(missing_ok=True)
            raise

    def path_for(self, parse_id: str, url: str) -> Path:
        safe_id = "".join(ch for ch in parse_id if ch.isalnum() or ch in {"-", "_"}) or "preview"
        suffix = ".mp4" if self.transcoder else self._suffix_from_url(url, ".mp4")
        return self.storage_root / "media" / "previews" / PREVIEW_CACHE_VERSION / f"{safe_id}{suffix}"

    def cleanup_preview_cache(self) -> None:
        root = self.storage_root / "media" / "previews" / PREVIEW_CACHE_VERSION
        if not root.exists():
            return
        now = time.time()
        files = [path for path in root.glob("*") if path.is_file()]
        for path in list(files):
            try:
                if now - path.stat().st_mtime > self.preview_cache_ttl_seconds:
                    path.unlink(missing_ok=True)
                    files.remove(path)
            except OSError:
                continue

        sized_files = []
        total = 0
        for path in files:
            try:
                stat = path.stat()
            except OSError:
                continue
            total += stat.st_size
            sized_files.append((stat.st_mtime, stat.st_size, path))
        if total <= self.preview_cache_max_bytes:
            return
        for _, size, path in sorted(sized_files):
            try:
                path.unlink(missing_ok=True)
                total -= size
            except OSError:
                continue
            if total <= self.preview_cache_max_bytes:
                break

    async def _fetch_to_path(self, url: str, path: Path, max_bytes: int, headers: Mapping[str, str]) -> str:
        total = 0
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code in {401, 403}:
                        raise MediaDownloadError(f"预览视频下载被平台拒绝: {response.status_code}")
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    with path.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > max_bytes:
                                raise MediaDownloadError("预览视频文件超过大小限制")
                            handle.write(chunk)
                    return content_type
        except httpx.TimeoutException as exc:
            raise MediaTimeoutError("预览视频下载超时") from exc
        except httpx.HTTPError as exc:
            raise MediaDownloadError(f"预览视频下载失败: {exc}") from exc

    @staticmethod
    def _suffix_from_url(url: str, default: str) -> str:
        suffix = Path(url.split("?", 1)[0]).suffix.lower()
        if suffix and len(suffix) <= 8:
            return suffix
        return default

    @classmethod
    def _is_browser_mp4(cls, path: Path, url: str, content_type: str) -> bool:
        if "mp4" in content_type.lower():
            return True
        if cls._suffix_from_url(url, "") == ".mp4":
            return True
        try:
            header = path.read_bytes()[:16]
        except OSError:
            return False
        return b"ftyp" in header


def resolve_ffmpeg_executable(configured_path: str = "") -> str:
    configured = configured_path.strip()
    if configured:
        return configured
    try:
        import imageio_ffmpeg  # type: ignore

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        found = shutil.which("ffmpeg")
        return found or "ffmpeg"


def build_ffmpeg_transcoder(ffmpeg_path: str = "", timeout_seconds: float = 120.0) -> TranscodePreview:
    executable = resolve_ffmpeg_executable(ffmpeg_path)

    async def transcode(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        command = [
            executable,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(target),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise MediaDownloadError("服务器未安装 ffmpeg，无法将 HEVC 视频转成可预览格式") from exc
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise MediaTimeoutError("预览视频转码超时") from exc
        if process.returncode != 0:
            detail = (stderr or stdout).decode("utf-8", errors="ignore").strip()
            raise MediaDownloadError(f"ffmpeg 转码失败: {detail or process.returncode}")

    return transcode
