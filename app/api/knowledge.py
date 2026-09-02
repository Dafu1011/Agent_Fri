from fastapi import APIRouter, HTTPException, Request

from app.api.auth import get_current_user_id
from app.knowledge import KnowledgeRepository
from app.schemas.knowledge import (
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def get_knowledge_repository(request: Request) -> KnowledgeRepository:
    repository = getattr(request.app.state, "knowledge_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Knowledge store is not available")
    return repository


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
