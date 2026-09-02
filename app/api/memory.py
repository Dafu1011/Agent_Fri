from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas.memory import (
    MemoryCreateRequest,
    MemoryDeleteResponse,
    MemoryListResponse,
    MemoryResponse,
)

router = APIRouter(prefix="/memories", tags=["memories"])


def get_memory_repository(request: Request):
    repository = getattr(request.app.state, "memory_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Memory store is not available")
    return repository


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    request: Request,
    user_id: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> MemoryListResponse:
    repository = get_memory_repository(request)
    return MemoryListResponse(memories=repository.list_memories(user_id, limit=limit))


@router.post("", response_model=MemoryResponse)
async def create_memory(
    payload: MemoryCreateRequest,
    request: Request,
) -> MemoryResponse:
    repository = get_memory_repository(request)
    return repository.add_memory(
        user_id=payload.user_id,
        content=payload.content,
        source_thread_id=payload.source_thread_id,
        kind=payload.kind,
        type=payload.type,
        title=payload.title,
        facts=payload.facts,
        concepts=payload.concepts,
    )


@router.delete("/{memory_id}", response_model=MemoryDeleteResponse)
async def delete_memory(
    memory_id: str,
    request: Request,
    user_id: str = Query(min_length=1),
) -> MemoryDeleteResponse:
    repository = get_memory_repository(request)
    deleted = repository.delete_memory(user_id=user_id, memory_id=memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return MemoryDeleteResponse(deleted=True)
