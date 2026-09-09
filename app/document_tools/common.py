from __future__ import annotations

from typing import Any

from .schemas import ConversionResult
from .storage import DocumentStorage


MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def store_document_result(
    storage: DocumentStorage,
    *,
    user_id: str,
    filename: str,
    mime_type: str,
    content: bytes,
    operation: str,
    message: str,
) -> ConversionResult:
    stored = storage.write_file(
        user_id=user_id,
        filename=filename,
        mime_type=mime_type,
        content=content,
        kind="generated",
    )
    download_url = f"/documents/files/{stored.file_id}/download"
    return ConversionResult(
        file_id=stored.file_id,
        filename=stored.filename,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        download_url=download_url,
        preview_url=download_url,
        operation=operation,
        message=message,
    )


def ensure_suffix(filename: str, suffix: str, fallback_stem: str) -> str:
    cleaned = (filename or "").strip()
    if not cleaned:
        cleaned = f"{fallback_stem}{suffix}"
    if not cleaned.lower().endswith(suffix):
        cleaned = f"{cleaned}{suffix}"
    return cleaned


def stringify_table(rows: list[list[Any]]) -> list[list[str]]:
    return [["" if value is None else str(value) for value in row] for row in rows]
