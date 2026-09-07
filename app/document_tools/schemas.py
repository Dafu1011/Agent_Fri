from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class StoredDocument:
    file_id: str
    user_id: str
    filename: str
    mime_type: str
    size_bytes: int
    path: Path
    kind: str


@dataclass(frozen=True)
class ConversionPlan:
    operation: str
    target_format: str
    output_suffix: str


@dataclass(frozen=True)
class ConversionResult:
    file_id: str
    filename: str
    mime_type: str
    size_bytes: int
    download_url: str
    preview_url: str
    operation: str
    message: str

    @property
    def attachment(self) -> dict[str, Any]:
        return {
            "platform": "document",
            "media_type": "file",
            "title": self.filename,
            "author": "",
            "cover": "",
            "video_url": "",
            "source_url": "",
            "images": [],
            "source_images": [],
            "parse_id": self.file_id,
            "file_id": self.file_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "download_url": self.download_url,
            "preview_url": self.preview_url,
            "size_bytes": self.size_bytes,
            "status": "ready",
            "message": self.message,
            "operation": self.operation,
        }


class UploadResponse(BaseModel):
    file_id: str
    filename: str
    mime_type: str
    size_bytes: int


class ConvertRequest(BaseModel):
    file_ids: list[str] = Field(default_factory=list)
    file_id: str = ""
    target_format: str = ""
    instruction: str = ""


class ConvertResponse(BaseModel):
    reply: str
    attachment: dict[str, Any]


class DocumentConversionError(Exception):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
