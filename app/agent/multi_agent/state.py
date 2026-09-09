from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages


class PlanStep(TypedDict):
    id: str
    description: str
    worker: str
    tool_names: list[str]
    status: Literal["pending", "running", "success", "failed"]


class WorkerOutput(TypedDict):
    step_id: str
    status: Literal["success", "failed"]
    summary: str


class MultiAgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    task: str
    user_id: str
    thread_id: str
    memories: list[str]
    knowledge: list[str]
    plan: list[PlanStep]
    selected_tool_names: list[str]
    worker_outputs: list[WorkerOutput]
    verification: dict[str, Any]
    attachments: list[dict[str, Any]]
    final_reply: str
