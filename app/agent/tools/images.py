from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from app.image_generation.service import ImageGenerationService


def build_image_generation_tools(user_id: str, service: ImageGenerationService) -> list[Any]:
    @tool("generate_image")
    async def generate_image(
        prompt: str,
        size: str = "",
        quality: str = "",
        count: int = 1,
    ) -> dict[str, Any]:
        """Generate images for the current user from a text prompt and return chat-renderable attachments."""
        result = await service.generate(
            user_id=user_id,
            prompt=prompt,
            size=size,
            quality=quality,
            count=count,
        )
        return {"message": result.message, "attachments": result.attachments}

    return [generate_image]
