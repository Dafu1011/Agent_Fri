from __future__ import annotations

import ast
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from app.agent.chat import generate_model_message
from app.agent.multi_agent.learning import LearningRepository
from app.agent.multi_agent.router import classify_task_route
from app.agent.multi_agent.state import MultiAgentState, PlanStep, WorkerOutput
from app.agent.tools.catalog import ToolCatalog

Planner = Callable[[MultiAgentState, ToolCatalog], Awaitable[dict[str, Any]]]
Worker = Callable[[MultiAgentState, list[Any]], Awaitable[dict[str, Any]]]
Verifier = Callable[[MultiAgentState], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class MultiAgentRunResult:
    reply: str
    attachments: list[dict[str, Any]]


def build_multi_agent_graph(
    *,
    tool_catalog: ToolCatalog,
    learning_repository: LearningRepository | None = None,
    planner: Planner | None = None,
    worker: Worker | None = None,
    verifier: Verifier | None = None,
):
    graph = StateGraph(MultiAgentState)

    async def plan_task_node(state: MultiAgentState) -> dict[str, Any]:
        if planner is not None:
            return await planner(state, tool_catalog)
        return _default_plan(state, tool_catalog)

    async def execute_worker_node(state: MultiAgentState) -> dict[str, Any]:
        selected_tools = tool_catalog.select_names(state.get("selected_tool_names", []))
        if worker is not None:
            return await worker(state, selected_tools)
        return await _default_worker_with_tools(state, selected_tools)

    async def verify_result_node(state: MultiAgentState) -> dict[str, Any]:
        if verifier is not None:
            return await verifier(state)
        return _default_verifier(state)

    async def report_result_node(state: MultiAgentState) -> dict[str, Any]:
        verification = state.get("verification", {})
        output_lines = [
            f"- {output['summary']}"
            for output in state.get("worker_outputs", [])
            if output.get("summary")
        ]
        reply = "\n".join(
            [
                verification.get("reason", "任务已处理。"),
                *output_lines,
            ]
        ).strip()
        return {"final_reply": reply or "任务已处理。"}

    async def save_learning_node(state: MultiAgentState) -> dict[str, Any]:
        if learning_repository is not None:
            learning_repository.save_from_state(state)
        return {}

    graph.add_node("plan_task", plan_task_node)
    graph.add_node("execute_worker", execute_worker_node)
    graph.add_node("verify_result", verify_result_node)
    graph.add_node("report_result", report_result_node)
    graph.add_node("save_learning", save_learning_node)
    graph.set_entry_point("plan_task")
    graph.add_edge("plan_task", "execute_worker")
    graph.add_edge("execute_worker", "verify_result")
    graph.add_edge("verify_result", "report_result")
    graph.add_edge("report_result", "save_learning")
    graph.add_edge("save_learning", END)
    return graph.compile()


async def run_multi_agent_graph(
    message: str,
    *,
    thread_id: str,
    user_id: str,
    graph: Any,
    memories: list[str] | None = None,
    knowledge: list[str] | None = None,
) -> str:
    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content=message)],
            "task": message,
            "user_id": user_id,
            "thread_id": thread_id,
            "memories": memories or [],
            "knowledge": knowledge or [],
            "plan": [],
            "selected_tool_names": [],
            "worker_outputs": [],
            "verification": {},
            "attachments": [],
            "final_reply": "",
        }
    )
    return str(result["final_reply"])


async def run_multi_agent_graph_with_result(
    message: str,
    *,
    thread_id: str,
    user_id: str,
    graph: Any,
    memories: list[str] | None = None,
    knowledge: list[str] | None = None,
) -> MultiAgentRunResult:
    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content=message)],
            "task": message,
            "user_id": user_id,
            "thread_id": thread_id,
            "memories": memories or [],
            "knowledge": knowledge or [],
            "plan": [],
            "selected_tool_names": [],
            "worker_outputs": [],
            "verification": {},
            "attachments": [],
            "final_reply": "",
        }
    )
    return MultiAgentRunResult(
        reply=str(result["final_reply"]),
        attachments=list(result.get("attachments", [])),
    )


def _default_plan(state: MultiAgentState, tool_catalog: ToolCatalog) -> dict[str, Any]:
    route = classify_task_route(
        state["task"],
        available_tool_names=tool_catalog.names(),
    )
    relevant_domains = set(route.domains)
    tool_names = [
        spec.name
        for spec in tool_catalog.specs
        if not relevant_domains or spec.domain in relevant_domains
    ]
    step: PlanStep = {
        "id": "step-1",
        "description": state["task"],
        "worker": "general_worker",
        "tool_names": tool_names,
        "status": "pending",
    }
    return {"plan": [step], "selected_tool_names": tool_names}


async def _default_worker_with_tools(
    state: MultiAgentState,
    selected_tools: list[Any],
) -> dict[str, Any]:
    if not selected_tools:
        return _default_worker(state)
    loop_result = await _run_model_tool_loop(state, selected_tools)
    outputs: list[WorkerOutput] = [
        {
            "step_id": step["id"],
            "status": "success",
            "summary": loop_result["summary"],
        }
        for step in state.get("plan", [])
    ]
    return {"worker_outputs": outputs, "attachments": loop_result["attachments"]}


async def _run_model_tool_loop(
    state: MultiAgentState,
    selected_tools: list[Any],
) -> dict[str, Any]:
    messages: list[Any] = [HumanMessage(content=_worker_prompt(state))]
    tool_node = ToolNode(selected_tools)
    attachments: list[dict[str, Any]] = []
    for _ in range(4):
        response = await generate_model_message(
            messages,
            memories=state.get("memories", []),
            knowledge=state.get("knowledge", []),
            tools=selected_tools,
        )
        messages.append(response)
        if not getattr(response, "tool_calls", None):
            return {"summary": str(response.content), "attachments": attachments}
        tool_result = await tool_node.ainvoke({"messages": [response]})
        tool_messages = tool_result.get("messages", [])
        attachments.extend(_extract_attachments_from_tool_messages(tool_messages))
        messages.extend(tool_messages)
    return {
        "summary": "工具调用轮次已达到上限，已停止继续执行。",
        "attachments": attachments,
    }


def _extract_attachments_from_tool_messages(messages: list[Any]) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        payload = _parse_tool_payload(message.content)
        if not isinstance(payload, dict):
            continue
        attachment = payload.get("attachment")
        if isinstance(attachment, dict):
            attachments.append(attachment)
        many = payload.get("attachments")
        if isinstance(many, list):
            attachments.extend(item for item in many if isinstance(item, dict))
    return attachments


def _parse_tool_payload(content: Any) -> Any:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(content)
        except (SyntaxError, ValueError):
            return None


def _worker_prompt(state: MultiAgentState) -> str:
    plan_lines = [
        f"{step['id']}. {step['description']} | worker={step['worker']} | tools={', '.join(step['tool_names'])}"
        for step in state.get("plan", [])
    ]
    return (
        "你是多 agent 编排中的执行 worker。请按照计划完成用户任务，"
        "只使用提供给你的工具。完成后用中文简洁总结结果。\n\n"
        f"用户任务：{state['task']}\n\n"
        "执行计划：\n"
        + "\n".join(plan_lines)
    )


def _default_worker(state: MultiAgentState) -> dict[str, Any]:
    outputs: list[WorkerOutput] = [
        {
            "step_id": step["id"],
            "status": "success",
            "summary": f"{step['worker']} 已规划处理：{step['description']}",
        }
        for step in state.get("plan", [])
    ]
    return {"worker_outputs": outputs}


def _default_verifier(state: MultiAgentState) -> dict[str, Any]:
    outputs = state.get("worker_outputs", [])
    passed = bool(outputs) and all(output.get("status") == "success" for output in outputs)
    return {
        "verification": {
            "passed": passed,
            "reason": "所有步骤成功完成" if passed else "任务未完成，需要继续处理。",
        }
    }
