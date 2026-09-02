from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source: str | None = None
    visibility: str = "private"


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_user_id: str | None
    title: str
    source: str | None
    visibility: str
    created_at: str


class KnowledgeSearchRequest(BaseModel):
    query: str = ""
    limit: int = Field(default=5, ge=1, le=20)


class KnowledgeSearchResponse(BaseModel):
    results: list[str]
