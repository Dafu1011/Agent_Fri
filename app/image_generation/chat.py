from __future__ import annotations

from typing import Any
import re

from .jobs import ImageGenerationJobStore


IMAGE_GENERATION_KEYWORDS = (
    "生成图片",
    "生成一张",
    "生成一个",
    "生图",
    "画一张",
    "画一个",
    "画个",
    "出图",
    "做一张图",
    "做张图",
)

IMAGE_GENERATION_ACTION_KEYWORDS = (
    "帮我生成",
    "生成",
    "generate",
    "create",
    "make",
)

VISUAL_PROMPT_KEYWORDS = (
    "图片",
    "图像",
    "照片",
    "海报",
    "封面",
    "头像",
    "插画",
    "壁纸",
    "photo",
    "image",
    "portrait",
    "poster",
    "illustration",
    "wallpaper",
    "photorealistic",
    "masterpiece",
)


def is_image_generation_request(message: str) -> bool:
    lowered = message.lower().replace(" ", "")
    if any(keyword.replace(" ", "") in lowered for keyword in IMAGE_GENERATION_KEYWORDS):
        return True
    has_generation_action = any(keyword.replace(" ", "") in lowered for keyword in IMAGE_GENERATION_ACTION_KEYWORDS)
    has_visual_prompt = any(keyword.replace(" ", "") in lowered for keyword in VISUAL_PROMPT_KEYWORDS)
    return has_generation_action and has_visual_prompt


def requested_image_count(message: str) -> int:
    match = re.search(r"(\d+)\s*张", message)
    if match:
        return int(match.group(1))
    return 1


async def parse_image_generation_message(
    message: str,
    user_id: str,
    job_store: ImageGenerationJobStore,
) -> dict[str, Any] | None:
    if not is_image_generation_request(message):
        return None
    job = job_store.create_job(
        user_id=user_id,
        prompt=message,
        count=requested_image_count(message),
    )
    return job.response_payload()
