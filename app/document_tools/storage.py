from __future__ import annotations

from pathlib import Path
import json
import re
import secrets
from typing import Any

from .schemas import StoredDocument


SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff ]+")


def safe_filename(filename: str) -> str:
    name = Path(filename or "uploaded-file").name.strip() or "uploaded-file"
    cleaned = SAFE_FILENAME_PATTERN.sub("_", name).strip(" .")
    return cleaned or "uploaded-file"


class DocumentStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def save_upload(
        self,
        *,
        user_id: str,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> StoredDocument:
        return self.write_file(
            user_id=user_id,
            filename=filename,
            mime_type=mime_type,
            content=content,
            kind="upload",
        )

    def write_file(
        self,
        *,
        user_id: str,
        filename: str,
        mime_type: str,
        content: bytes,
        kind: str,
    ) -> StoredDocument:
        file_id = f"file-{secrets.token_urlsafe(16)}"
        safe_name = safe_filename(filename)
        directory = self.root / "documents" / user_id / file_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / safe_name
        path.write_bytes(content)
        stored = StoredDocument(
            file_id=file_id,
            user_id=user_id,
            filename=safe_name,
            mime_type=mime_type or "application/octet-stream",
            size_bytes=len(content),
            path=path,
            kind=kind,
        )
        (directory / "metadata.json").write_text(
            json.dumps(
                {
                    "file_id": stored.file_id,
                    "user_id": stored.user_id,
                    "filename": stored.filename,
                    "mime_type": stored.mime_type,
                    "size_bytes": stored.size_bytes,
                    "path": str(stored.path),
                    "kind": stored.kind,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return stored

    def get_file(self, user_id: str, file_id: str) -> StoredDocument | None:
        if not self._is_safe_file_id(file_id):
            return None
        directory = (self.root / "documents" / user_id / file_id).resolve()
        metadata_path = directory / "metadata.json"
        if not metadata_path.exists():
            return None
        try:
            data: dict[str, Any] = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            path = Path(str(data.get("path") or "")).resolve()
        except OSError:
            return None
        if not path.is_relative_to(directory):
            return None
        if not path.exists():
            return None
        return StoredDocument(
            file_id=str(data.get("file_id") or file_id),
            user_id=str(data.get("user_id") or user_id),
            filename=str(data.get("filename") or path.name),
            mime_type=str(data.get("mime_type") or "application/octet-stream"),
            size_bytes=int(data.get("size_bytes") or path.stat().st_size),
            path=path,
            kind=str(data.get("kind") or "upload"),
        )

    @staticmethod
    def _is_safe_file_id(file_id: str) -> bool:
        return bool(re.fullmatch(r"file-[A-Za-z0-9_\-]+", file_id or ""))
