from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.auth import get_current_user_id
from app.document_tools.api.document_router import get_document_storage
from app.knowledge import KnowledgeRepository
from app.knowledge_ingestion import KnowledgeIngestionService
from app.schemas.knowledge import (
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgeIngestFilesRequest(BaseModel):
    file_ids: list[str] = Field(default_factory=list)
    instruction: str = ""
    visibility: str = "private"


class KnowledgeIngestFilesResponse(BaseModel):
    reply: str
    results: list[dict[str, Any]]


def get_knowledge_repository(request: Request) -> KnowledgeRepository:
    repository = getattr(request.app.state, "knowledge_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Knowledge store is not available")
    return repository


def get_knowledge_ingestion_service(request: Request) -> KnowledgeIngestionService:
    repository = get_knowledge_repository(request)
    return KnowledgeIngestionService(
        storage=get_document_storage(request),
        document_service=getattr(request.app.state, "document_conversion_service", None),
        knowledge_repository=repository,
    )


@router.post("/documents", response_model=KnowledgeDocumentResponse)
async def create_document(
    payload: KnowledgeDocumentCreateRequest,
    request: Request,
) -> KnowledgeDocumentResponse:
    user_id = get_current_user_id(request)
    try:
        return get_knowledge_repository(request).add_document(
            owner_user_id=user_id,
            title=payload.title,
            content=payload.content,
            source=payload.source,
            visibility=payload.visibility,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/ingest-files", response_model=KnowledgeIngestFilesResponse)
async def ingest_files(
    payload: KnowledgeIngestFilesRequest,
    request: Request,
) -> KnowledgeIngestFilesResponse:
    user_id = get_current_user_id(request)
    if not payload.file_ids:
        raise HTTPException(status_code=422, detail="请先上传需要入库的文件。")
    if payload.visibility not in {"private", "public"}:
        raise HTTPException(status_code=422, detail="visibility must be private or public")
    try:
        result = get_knowledge_ingestion_service(request).ingest_files(
            user_id=user_id,
            file_ids=payload.file_ids,
            instruction=payload.instruction,
            visibility=payload.visibility,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return KnowledgeIngestFilesResponse(
        reply=result.reply,
        results=[item.__dict__ for item in result.results],
    )


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    payload: KnowledgeSearchRequest,
    request: Request,
) -> KnowledgeSearchResponse:
    user_id = get_current_user_id(request)
    results = get_knowledge_repository(request).search(
        user_id=user_id,
        query=payload.query,
        limit=payload.limit,
    )
    return KnowledgeSearchResponse(results=results)
