from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.auth import get_current_user_id
from app.config import settings
from app.document_tools.schemas import ConvertRequest, ConvertResponse, DocumentConversionError, UploadResponse
from app.document_tools.service import DocumentConversionService
from app.document_tools.storage import DocumentStorage


router = APIRouter(tags=["document-tools"])


def get_document_storage(request: Request) -> DocumentStorage:
    storage = getattr(request.app.state, "document_storage", None)
    if storage is None:
        storage = DocumentStorage(settings.storage_path)
        request.app.state.document_storage = storage
    return storage


def get_document_conversion_service(request: Request) -> DocumentConversionService:
    service = getattr(request.app.state, "document_conversion_service", None)
    if service is None:
        service = DocumentConversionService(get_document_storage(request))
        request.app.state.document_conversion_service = service
    return service


@router.post("/files/upload", response_model=UploadResponse)
async def upload_file(request: Request, file: UploadFile = File(...)) -> UploadResponse:
    user_id = get_current_user_id(request)
    max_upload_mb = max(1, settings.document_max_upload_mb)
    max_bytes = max_upload_mb * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"上传文件超过 {max_upload_mb} MB 限制")
    stored = get_document_storage(request).save_upload(
        user_id=user_id,
        filename=file.filename or "uploaded-file",
        mime_type=file.content_type or "application/octet-stream",
        content=content,
    )
    return UploadResponse(
        file_id=stored.file_id,
        filename=stored.filename,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
    )


@router.post("/documents/convert", response_model=ConvertResponse)
async def convert_document(payload: ConvertRequest, request: Request) -> ConvertResponse:
    user_id = get_current_user_id(request)
    file_ids = payload.file_ids or ([payload.file_id] if payload.file_id else [])
    try:
        result = get_document_conversion_service(request).convert(
            user_id=user_id,
            file_ids=file_ids,
            instruction=payload.instruction,
            target_format=payload.target_format,
        )
    except DocumentConversionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return ConvertResponse(reply=result.message, attachment=result.attachment)


@router.get("/documents/files/{file_id}/download")
async def download_document(file_id: str, request: Request) -> FileResponse:
    user_id = get_current_user_id(request)
    stored = get_document_storage(request).get_file(user_id, file_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        stored.path,
        filename=stored.filename,
        media_type=stored.mime_type,
    )
