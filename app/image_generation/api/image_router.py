from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.api.auth import get_current_user_id
from app.config import settings
from app.image_generation.jobs import ImageGenerationJobStore
from app.image_generation.schemas import ImageGenerationJobResponse, ImageGenerationRequest
from app.image_generation.service import ImageGenerationService
from app.image_generation.storage import ImageGenerationStorage


router = APIRouter(prefix="/images", tags=["image-generation"])


def get_image_generation_storage(request: Request) -> ImageGenerationStorage:
    storage = getattr(request.app.state, "image_generation_storage", None)
    if storage is None:
        storage = ImageGenerationStorage(settings.storage_path)
        request.app.state.image_generation_storage = storage
    return storage


def get_image_generation_service(request: Request) -> ImageGenerationService:
    service = getattr(request.app.state, "image_generation_service", None)
    if service is None:
        service = ImageGenerationService(get_image_generation_storage(request))
        request.app.state.image_generation_service = service
    return service


def get_image_generation_job_store(request: Request) -> ImageGenerationJobStore:
    job_store = getattr(request.app.state, "image_generation_job_store", None)
    if job_store is None:
        job_store = ImageGenerationJobStore(get_image_generation_service(request))
        request.app.state.image_generation_job_store = job_store
    return job_store


@router.post("/generate", response_model=ImageGenerationJobResponse)
async def generate_image(payload: ImageGenerationRequest, request: Request) -> ImageGenerationJobResponse:
    user_id = get_current_user_id(request)
    job = get_image_generation_job_store(request).create_job(
        user_id=user_id,
        prompt=payload.prompt,
        size=payload.size,
        quality=payload.quality,
        count=payload.count,
    )
    return ImageGenerationJobResponse(**job.response_payload())


@router.get("/jobs/{job_id}", response_model=ImageGenerationJobResponse)
async def image_generation_job(job_id: str, request: Request) -> ImageGenerationJobResponse:
    user_id = get_current_user_id(request)
    job = get_image_generation_job_store(request).get_job(user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Image generation job not found")
    return ImageGenerationJobResponse(**job.response_payload())


@router.get("/files/{image_id}")
async def generated_image(image_id: str, request: Request) -> FileResponse:
    user_id = get_current_user_id(request)
    image = get_image_generation_storage(request).get_image(user_id, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(image.path, media_type=image.mime_type)


@router.get("/files/{image_id}/download")
async def download_generated_image(image_id: str, request: Request) -> FileResponse:
    user_id = get_current_user_id(request)
    image = get_image_generation_storage(request).get_image(user_id, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(image.path, filename=image.filename, media_type=image.mime_type)
