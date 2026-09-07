from __future__ import annotations

from pathlib import Path
import json
import re
import secrets
from typing import Any

from .schemas import GeneratedImage


SAFE_IMAGE_ID_PATTERN = re.compile(r"img-[A-Za-z0-9_\-]+")


class ImageGenerationStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def save_image(
        self,
        *,
        user_id: str,
        prompt: str,
        content: bytes,
        mime_type: str,
        model: str,
        size: str,
        quality: str,
        revised_prompt: str = "",
        filename: str = "image.png",
    ) -> GeneratedImage:
        image_id = f"img-{secrets.token_urlsafe(16)}"
        directory = self.root / "generated_images" / user_id / image_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        path.write_bytes(content)
        image = GeneratedImage(
            image_id=image_id,
            user_id=user_id,
            filename=filename,
            mime_type=mime_type or "image/png",
            size_bytes=len(content),
            path=path,
            prompt=prompt,
            model=model,
            size=size,
            quality=quality,
            revised_prompt=revised_prompt,
        )
        (directory / "metadata.json").write_text(
            json.dumps(
                {
                    "image_id": image.image_id,
                    "user_id": image.user_id,
                    "filename": image.filename,
                    "mime_type": image.mime_type,
                    "size_bytes": image.size_bytes,
                    "path": str(image.path),
                    "prompt": image.prompt,
                    "model": image.model,
                    "size": image.size,
                    "quality": image.quality,
                    "revised_prompt": image.revised_prompt,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return image

    def get_image(self, user_id: str, image_id: str) -> GeneratedImage | None:
        if not SAFE_IMAGE_ID_PATTERN.fullmatch(image_id or ""):
            return None
        directory = (self.root / "generated_images" / user_id / image_id).resolve()
        metadata_path = directory / "metadata.json"
        if not metadata_path.exists():
            return None
        try:
            data: dict[str, Any] = json.loads(metadata_path.read_text(encoding="utf-8"))
            path = Path(str(data.get("path") or "")).resolve()
        except (OSError, json.JSONDecodeError):
            return None
        if not path.is_relative_to(directory) or not path.exists():
            return None
        return GeneratedImage(
            image_id=str(data.get("image_id") or image_id),
            user_id=str(data.get("user_id") or user_id),
            filename=str(data.get("filename") or path.name),
            mime_type=str(data.get("mime_type") or "image/png"),
            size_bytes=int(data.get("size_bytes") or path.stat().st_size),
            path=path,
            prompt=str(data.get("prompt") or ""),
            model=str(data.get("model") or ""),
            size=str(data.get("size") or ""),
            quality=str(data.get("quality") or ""),
            revised_prompt=str(data.get("revised_prompt") or ""),
        )
