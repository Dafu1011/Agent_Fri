from pydantic import BaseModel, Field


class MediaAttachment(BaseModel):
    platform: str
    media_type: str
    title: str = ""
    author: str = ""
    cover: str = ""
    video_url: str = ""
    source_url: str = ""
    images: list[str] = Field(default_factory=list)
    source_images: list[str] = Field(default_factory=list)
    parse_id: str = ""


class ChatRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    reply: str
    attachments: list[MediaAttachment] = Field(default_factory=list)


class ChatHistoryMessage(BaseModel):
    role: str
    text: str
    attachments: list[MediaAttachment] = Field(default_factory=list)


class ChatHistoryResponse(BaseModel):
    messages: list[ChatHistoryMessage]
