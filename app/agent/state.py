import operator
from typing import Annotated, Literal, TypedDict


class ChatMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class ChatState(TypedDict):
    # LangGraph appends new messages to checkpointed history across turns.
    messages: Annotated[list[ChatMessage], operator.add]
    reply: str
    user_id: str
    thread_id: str
    memories: list[str]
