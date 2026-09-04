import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
import httpx
from pydantic import ValidationError

from app.config import settings

from ..core.concurrency import ConcurrencyLimitExceeded
from ..core.detector import detect_platform
from ..core.errors import InvalidMediaUrlError, MediaDownloaderError
from ..core.extractor import MediaExtractorService, build_media_extractor_service
from ..core.headers import build_media_resource_headers
from ..core.streamer import MediaPreviewStreamer, build_ffmpeg_transcoder
from ..schemas.media import MediaApiResponse, MediaInfo, MediaParseRequest


router = APIRouter(prefix="/media", tags=["media-downloader"])


def get_media_extractor_service() -> MediaExtractorService:
    return build_media_extractor_service(settings.storage_path)


def get_media_preview_streamer() -> MediaPreviewStreamer:
    return MediaPreviewStreamer(
        settings.storage_path,
        transcoder=build_ffmpeg_transcoder(
            settings.media_ffmpeg_path,
            settings.media_download_timeout_seconds,
        )
        if settings.media_preview_transcode_enabled
        else None,
        timeout_seconds=settings.media_download_timeout_seconds,
        max_preview_mb=settings.media_max_download_mb,
        preview_cache_ttl_seconds=settings.media_preview_cache_ttl_seconds,
        preview_cache_max_mb=settings.media_preview_cache_max_mb,
    )


def map_media_error(exc: MediaDownloaderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def media_preview_payload(info: MediaInfo, parse_id: str) -> dict:
    data = info.model_dump(mode="json")
    data["parse_id"] = parse_id
    data["preview_url"] = f"/media/preview/{parse_id}" if info.video_url else ""
    data["image_preview_urls"] = [
        f"/media/image/{parse_id}/{index}" for index, _image in enumerate(info.images)
    ]
    data["can_download"] = bool(info.video_url or info.images)
    return data


async def read_body_text(request: Request) -> str:
    body = await request.body()
    return body.decode("utf-8", errors="ignore").strip()


async def read_parse_request(request: Request) -> MediaParseRequest:
    text = await read_body_text(request)
    if not text:
        raise InvalidMediaUrlError("请输入分享链接")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return MediaParseRequest(url=text)
    try:
        if isinstance(payload, dict):
            value = payload.get("url") or payload.get("text") or payload.get("share_text")
            return MediaParseRequest(url=str(value or text))
        if isinstance(payload, str):
            return MediaParseRequest(url=payload)
        return MediaParseRequest(url=text)
    except ValidationError as exc:
        raise InvalidMediaUrlError("请输入分享链接") from exc


@router.post("/detect", response_model=MediaApiResponse)
async def detect_media(request: Request) -> MediaApiResponse:
    try:
        payload = await read_parse_request(request)
        return MediaApiResponse(data=detect_platform(payload.url).model_dump(mode="json"))
    except MediaDownloaderError as exc:
        raise map_media_error(exc) from exc


@router.post("/parse", response_model=MediaApiResponse)
async def parse_media(
    request: Request,
    service: MediaExtractorService = Depends(get_media_extractor_service),
) -> MediaApiResponse:
    try:
        payload = await read_parse_request(request)
        info = await service.parse(payload.url)
        return MediaApiResponse(data=media_preview_payload(info, service.parse_id_for(payload.url)))
    except ConcurrencyLimitExceeded as exc:
        raise map_media_error(exc) from exc
    except MediaDownloaderError as exc:
        raise map_media_error(exc) from exc


@router.get("/preview/{parse_id}")
async def preview_media(
    parse_id: str,
    request: Request,
    service: MediaExtractorService = Depends(get_media_extractor_service),
    streamer: MediaPreviewStreamer = Depends(get_media_preview_streamer),
):
    try:
        info = service.get_cached_parse(parse_id)
        return await streamer.stream(info, parse_id, request.headers.get("range", ""))
    except ConcurrencyLimitExceeded as exc:
        raise map_media_error(exc) from exc
    except MediaDownloaderError as exc:
        raise map_media_error(exc) from exc


@router.get("/image/{parse_id}/{image_index}")
async def preview_image(
    parse_id: str,
    image_index: int,
    service: MediaExtractorService = Depends(get_media_extractor_service),
):
    try:
        info = service.get_cached_parse(parse_id)
        if image_index < 0 or image_index >= len(info.images):
            raise InvalidMediaUrlError("图片索引不存在")
        url = info.images[image_index]
        async with httpx.AsyncClient(timeout=settings.media_download_timeout_seconds, follow_redirects=True) as client:
            response = await client.get(url, headers=build_media_resource_headers(info))
        response.raise_for_status()
        return Response(
            content=response.content,
            media_type=response.headers.get("content-type") or "image/jpeg",
            headers={"Cache-Control": "private, max-age=300"},
        )
    except httpx.HTTPError as exc:
        raise map_media_error(MediaDownloaderError(f"图片预览加载失败: {exc}")) from exc
    except MediaDownloaderError as exc:
        raise map_media_error(exc) from exc
