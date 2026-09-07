from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class GeneratedImage:
    image_id: str
    user_id: str
    filename: str
    mime_type: str
    size_bytes: int
    path: Path
    prompt: str
    model: str
    size: str
    quality: str
    revised_prompt: str = ""

    @property
    def attachment(self) -> dict[str, Any]:
        return {
            "platform": "image-generation",
            "media_type": "generated_image",
            "title": self.prompt,
            "author": self.model,
            "cover": f"/images/files/{self.image_id}",
            "video_url": "",
            "source_url": "",
            "images": [],
            "source_images": [],
            "parse_id": self.image_id,
            "image_id": self.image_id,
            "image_url": f"/images/files/{self.image_id}",
            "download_url": f"/images/files/{self.image_id}/download",
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "prompt": self.prompt,
            "revised_prompt": self.revised_prompt,
            "model": self.model,
            "size": self.size,
            "quality": self.quality,
            "status": "ready",
            "message": "图片已生成。",
        }


@dataclass(frozen=True)
class GeneratedImagePayload:
    content: bytes
    revised_prompt: str = ""
    mime_type: str = "image/png"


@dataclass(frozen=True)
class ImageGenerationResult:
    images: list[GeneratedImage]
    message: str = "图片已生成。"

    @property
    def attachments(self) -> list[dict[str, Any]]:
        return [image.attachment for image in self.images]


@dataclass
class ImageGenerationJob:
    job_id: str
    user_id: str
    prompt: str
    size: str
    quality: str
    count: int
    status: str = "queued"
    reply: str = "已开始生成图片，我会在完成后展示。"
    attachments: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    @property
    def attachment(self) -> dict[str, Any]:
        return {
            "platform": "image-generation",
            "media_type": "image_generation_job",
            "title": "图片生成中",
            "author": "",
            "cover": "",
            "video_url": "",
            "source_url": "",
            "images": [],
            "source_images": [],
            "parse_id": self.job_id,
            "job_id": self.job_id,
            "status": self.status,
            "poll_url": f"/images/jobs/{self.job_id}",
            "prompt": self.prompt,
            "size": self.size,
            "quality": self.quality,
            "count": self.count,
            "message": self.error or self.reply,
        }

    def response_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "reply": self.reply,
            "attachments": self.attachments if self.status == "ready" else [self.attachment],
            "error": self.error,
        }


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(min_length=1)
    size: str = ""
    quality: str = ""
    count: int = Field(default=1, ge=1)


class ImageGenerationJobResponse(BaseModel):
    job_id: str
    status: str
    reply: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    error: str = ""


class ImageGenerationError(Exception):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
