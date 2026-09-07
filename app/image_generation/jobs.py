from __future__ import annotations

import asyncio
import secrets

from .schemas import ImageGenerationJob, ImageGenerationError
from .service import ImageGenerationService


class ImageGenerationJobStore:
    def __init__(self, service: ImageGenerationService):
        self.service = service
        self._jobs: dict[str, ImageGenerationJob] = {}

    def create_job(
        self,
        *,
        user_id: str,
        prompt: str,
        size: str = "",
        quality: str = "",
        count: int = 1,
    ) -> ImageGenerationJob:
        job = ImageGenerationJob(
            job_id=f"imgjob-{secrets.token_urlsafe(16)}",
            user_id=user_id,
            prompt=prompt.strip(),
            size=size,
            quality=quality,
            count=count,
        )
        self._jobs[job.job_id] = job
        try:
            asyncio.create_task(self._run(job))
        except RuntimeError:
            job.status = "failed"
            job.error = "图片生成任务启动失败：当前没有可用事件循环。"
            job.reply = f"图片生成失败：{job.error}"
        return job

    def get_job(self, user_id: str, job_id: str) -> ImageGenerationJob | None:
        job = self._jobs.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    async def wait_for_progress(self) -> None:
        await asyncio.sleep(0.01)

    async def _run(self, job: ImageGenerationJob) -> None:
        job.status = "running"
        try:
            result = await self.service.generate(
                user_id=job.user_id,
                prompt=job.prompt,
                size=job.size,
                quality=job.quality,
                count=job.count,
            )
        except ImageGenerationError as exc:
            job.status = "failed"
            job.error = exc.message
            job.reply = f"图片生成失败：{exc.message}"
            return
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.reply = f"图片生成失败：{exc}"
            return

        job.status = "ready"
        job.reply = result.message
        job.attachments = result.attachments
