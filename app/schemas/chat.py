from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    reply: str


class ChatHistoryMessage(BaseModel):
    role: str
    text: str


class ChatHistoryResponse(BaseModel):
    messages: list[ChatHistoryMessage]
