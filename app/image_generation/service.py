from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
import base64

import httpx

from app.config import settings

from .schemas import GeneratedImagePayload, ImageGenerationError, ImageGenerationResult
from .storage import ImageGenerationStorage


def _safe_url_for_error(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return url[:120]
    safe_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if len(safe_url) > 160:
        return f"{safe_url[:157]}..."
    return safe_url


class ImageGenerationClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @classmethod
    def from_settings(cls) -> "ImageGenerationClient":
        api_key = settings.image_openai_api_key.strip()
        if not api_key:
            raise ImageGenerationError("IMAGE_OPENAI_API_KEY is not configured", status_code=503)
        return cls(
            api_key=api_key,
            base_url=(settings.image_openai_base_url or "https://api.openai.com/v1"),
            model=settings.image_generation_model,
            timeout_seconds=max(1, settings.image_generation_timeout_seconds),
        )

    async def generate(
        self,
        *,
        prompt: str,
        size: str,
        quality: str,
        count: int,
    ) -> list[GeneratedImagePayload]:
        request_body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": count,
        }
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            try:
                response = await client.post(
                    "/images/generations",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=request_body,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text.strip()
                raise ImageGenerationError(
                    f"图片生成接口返回错误：{detail or exc.response.status_code}",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.TimeoutException as exc:
                raise ImageGenerationError(
                    f"图片生成接口请求超时：{self.timeout_seconds} 秒内没有收到响应。请调大 IMAGE_GENERATION_TIMEOUT_SECONDS，或检查生图网关排队/模型耗时。",
                    status_code=504,
                ) from exc
            except httpx.HTTPError as exc:
                detail = str(exc) or type(exc).__name__
                raise ImageGenerationError(f"图片生成接口请求失败：{detail}", status_code=503) from exc

            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list) or not data:
                raise ImageGenerationError("图片生成接口没有返回图片数据。", status_code=502)

            images: list[GeneratedImagePayload] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                revised_prompt = str(item.get("revised_prompt") or "")
                encoded = item.get("b64_json")
                if isinstance(encoded, str) and encoded:
                    try:
                        content = base64.b64decode(encoded)
                    except ValueError as exc:
                        raise ImageGenerationError("图片生成接口返回了无效的图片数据。", status_code=502) from exc
                    images.append(
                        GeneratedImagePayload(
                            content=content,
                            revised_prompt=revised_prompt,
                            mime_type=f"image/{settings.image_generation_default_format.strip().lower() or 'png'}",
                        )
                    )
                    continue

                image_url = item.get("url")
                if not isinstance(image_url, str) or not image_url.strip():
                    continue
                try:
                    image_response = await client.get(image_url.strip())
                    image_response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    detail = exc.response.text.strip()
                    raise ImageGenerationError(
                        f"图片下载接口返回错误：{detail or exc.response.status_code}",
                        status_code=exc.response.status_code,
                    ) from exc
                except httpx.TimeoutException as exc:
                    raise ImageGenerationError(
                        f"图片下载请求超时：{self.timeout_seconds} 秒内没有收到响应。",
                        status_code=504,
                    ) from exc
                except httpx.HTTPError as exc:
                    detail = str(exc) or type(exc).__name__
                    safe_url = _safe_url_for_error(image_url)
                    raise ImageGenerationError(f"图片下载失败：{safe_url}，{detail}", status_code=503) from exc

                mime_type = image_response.headers.get("content-type", "application/octet-stream")
                images.append(
                    GeneratedImagePayload(
                        content=image_response.content,
                        revised_prompt=revised_prompt,
                        mime_type=mime_type.split(";", 1)[0].strip() or "application/octet-stream",
                    )
                )

            if not images:
                raise ImageGenerationError("图片生成接口没有返回可用的图片数据。", status_code=502)
            return images


class ImageGenerationService:
    def __init__(
        self,
        storage: ImageGenerationStorage,
        *,
        client: ImageGenerationClient | None = None,
    ):
        self.storage = storage
        self.client = client

    def _client(self) -> ImageGenerationClient:
        if self.client is None:
            self.client = ImageGenerationClient.from_settings()
        return self.client

    async def generate(
        self,
        *,
        user_id: str,
        prompt: str,
        size: str = "",
        quality: str = "",
        count: int = 1,
    ) -> ImageGenerationResult:
        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise ImageGenerationError("请输入图片生成提示词。")

        image_count = min(max(1, count), max(1, settings.image_generation_max_images))
        image_size = size.strip() or settings.image_generation_default_size
        image_quality = quality.strip() or settings.image_generation_default_quality
        client = self._client()
        payloads = await client.generate(
            prompt=normalized_prompt,
            size=image_size,
            quality=image_quality,
            count=image_count,
        )
        images = []
        extension = settings.image_generation_default_format.strip().lower() or "png"
        model = getattr(client, "model", settings.image_generation_model)
        for index, payload in enumerate(payloads):
            filename = "image.png" if len(payloads) == 1 else f"image-{index + 1}.{extension}"
            images.append(
                self.storage.save_image(
                    user_id=user_id,
                    prompt=normalized_prompt,
                    content=payload.content,
                    mime_type=payload.mime_type,
                    model=model,
                    size=image_size,
                    quality=image_quality,
                    revised_prompt=payload.revised_prompt,
                    filename=filename,
                )
            )
        return ImageGenerationResult(images=images)
