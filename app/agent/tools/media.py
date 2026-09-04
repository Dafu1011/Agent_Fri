from typing import Any

from langchain_core.tools import tool

from app.media_downloader.api.media_router import media_preview_payload
from app.media_downloader.core.extractor import build_media_extractor_service
from app.config import settings


async def parse_social_media_link_data(url_or_text: str) -> dict[str, Any]:
    service = build_media_extractor_service(settings.storage_path)
    info = await service.parse(url_or_text)
    return media_preview_payload(info, service.parse_id_for(url_or_text))


def build_media_parse_tool():
    @tool("parse_social_media_link")
    async def parse_social_media_link(url_or_text: str) -> dict[str, Any]:
        """Parse a public Douyin, Kuaishou, or Xiaohongshu share link and return video or image preview metadata."""
        return await parse_social_media_link_data(url_or_text)

    return parse_social_media_link


def build_media_tools() -> list[Any]:
    return [build_media_parse_tool()]
