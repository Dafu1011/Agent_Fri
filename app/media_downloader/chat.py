from __future__ import annotations

from typing import Any

from app.media_downloader.api.media_router import media_preview_payload
from app.media_downloader.core.detector import normalize_share_url
from app.media_downloader.core.errors import MediaDownloaderError
from app.media_downloader.core.extractor import build_media_extractor_service
from app.config import settings


PARSE_KEYWORDS = ("解析", "parse", "提取", "抓取")


def is_media_parse_request(message: str) -> bool:
    try:
        normalize_share_url(message)
    except MediaDownloaderError:
        return False
    lowered = message.lower()
    return any(keyword in lowered for keyword in PARSE_KEYWORDS)


def build_media_attachment(payload: dict[str, Any]) -> dict[str, Any]:
    media_type = str(payload.get("type") or "")
    return {
        "platform": str(payload.get("platform") or ""),
        "media_type": "image_gallery" if media_type == "images" else media_type,
        "title": str(payload.get("title") or ""),
        "author": str(payload.get("author") or ""),
        "cover": str(payload.get("cover") or ""),
        "video_url": str(payload.get("preview_url") or payload.get("video_url") or ""),
        "source_url": str(payload.get("video_url") or ""),
        "images": [str(item) for item in payload.get("image_preview_urls") or payload.get("images") or []],
        "source_images": [str(item) for item in payload.get("images") or []],
        "parse_id": str(payload.get("parse_id") or ""),
    }


def build_success_reply(attachment: dict[str, Any]) -> str:
    platform_names = {
        "douyin": "抖音",
        "xiaohongshu": "小红书",
        "kuaishou": "快手",
    }
    platform = platform_names.get(attachment["platform"], attachment["platform"] or "该平台")
    title = attachment["title"] or "未命名作品"
    if attachment["media_type"] == "video":
        return f"已解析到{platform}视频：{title}。"
    count = len(attachment["images"])
    return f"已解析到{platform}图集：{title}，共 {count} 张图片。"


def build_failure_reply(exc: MediaDownloaderError) -> str:
    return f"解析失败：{exc.message}"


async def parse_media_message(message: str) -> dict[str, Any] | None:
    if not is_media_parse_request(message):
        return None
    service = build_media_extractor_service(settings.storage_path)
    try:
        info = await service.parse(message)
        payload = media_preview_payload(info, service.parse_id_for(message))
    except MediaDownloaderError as exc:
        return {"reply": build_failure_reply(exc), "attachments": []}
    attachment = build_media_attachment(payload)
    return {"reply": build_success_reply(attachment), "attachments": [attachment]}
