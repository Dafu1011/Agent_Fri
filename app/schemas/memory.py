from pydantic import BaseModel, ConfigDict, Field


class MemoryCreateRequest(BaseModel):
    user_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source_thread_id: str | None = None
    kind: str = "manual"
    type: str = "note"
    title: str | None = None
    facts: list[str] | None = None
    concepts: list[str] | None = None


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content: str
    source_thread_id: str | None
    created_at: str
    updated_at: str
    kind: str
    type: str
    title: str | None
    facts: list[str] | None
    concepts: list[str] | None


class MemoryListResponse(BaseModel):
    memories: list[MemoryResponse]


class MemoryDeleteResponse(BaseModel):
    deleted: bool
