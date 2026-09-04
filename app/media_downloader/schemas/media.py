from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


PlatformValue = Literal["douyin", "xiaohongshu", "kuaishou"]
MediaTypeValue = Literal["video", "images", "mixed"]


class PlatformDetection(BaseModel):
    platform: PlatformValue
    normalized_url: str


class MediaParseRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4000)


class MediaDownloadRequest(BaseModel):
    url: str | None = Field(default=None, min_length=1, max_length=4000)
    parse_id: str | None = Field(default=None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def ensure_download_source(self) -> "MediaDownloadRequest":
        if not self.url and not self.parse_id:
            raise ValueError("url or parse_id is required")
        return self


class MediaInfo(BaseModel):
    platform: PlatformValue
    type: MediaTypeValue
    title: str = ""
    author: str = ""
    cover: str = ""
    video_url: str = ""
    images: list[str] = Field(default_factory=list)
    duration: int | None = None
    create_time: datetime | str | None = None
    download_url: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_media_payload(self) -> "MediaInfo":
        if self.type == "video" and not self.video_url:
            raise ValueError("video media requires video_url")
        if self.type == "images" and not self.images:
            raise ValueError("image media requires at least one image")
        if self.type == "mixed" and not (self.video_url or self.images):
            raise ValueError("mixed media requires video_url or images")
        if not self.download_url and self.video_url:
            self.download_url = self.video_url
        return self


class MediaApiResponse(BaseModel):
    success: bool = True
    data: Any


class DownloadedFile(BaseModel):
    path: str
    url: str
    asset: dict[str, Any]


class MediaDownloadResult(BaseModel):
    path: str = ""
    url: str = ""
    asset: dict[str, Any] | None = None
    files: list[DownloadedFile] = Field(default_factory=list)
