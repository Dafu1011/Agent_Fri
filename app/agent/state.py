from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages


class ChatMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class ChatState(TypedDict):
    # LangGraph appends new messages to checkpointed history across turns.
    messages: Annotated[list[AnyMessage], add_messages]
    reply: str
    user_id: str
    thread_id: str
    memories: list[str]
    knowledge: list[str]
