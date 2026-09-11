from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import HumanMessage

from app.agent.chat import generate_model_message
from app.agent.multi_agent.router import TaskPath, classify_task_route
from app.agent.tools.catalog import ToolCatalog


WorkerName = Literal[
    "general_worker",
    "vision_worker",
    "image_worker",
    "document_worker",
    "media_worker",
    "research_worker",
]


@dataclass(frozen=True)
class InputAttachment:
    file_id: str
    filename: str = ""
    mime_type: str = ""
    size_bytes: int = 0

    @property
    def kind(self) -> str:
        if self.mime_type.startswith("image/"):
            return "image"
        if self.mime_type in {"application/pdf"} or self.filename.lower().endswith(".pdf"):
            return "pdf"
        if self.filename.lower().endswith((".doc", ".docx")):
            return "word"
        if self.filename.lower().endswith((".xls", ".xlsx", ".csv")):
            return "spreadsheet"
        return "file"


@dataclass(frozen=True)
class ModelRouteDecision:
    path: TaskPath
    intent: str
    worker: WorkerName
    tool_names: list[str]
    needs_memory: bool
    needs_knowledge: bool
    confidence: float
    reason: str


async def decide_route(
    message: str,
    *,
    attachments: list[InputAttachment] | None = None,
    tool_catalog: ToolCatalog,
) -> ModelRouteDecision:
    """Use one cheap routing decision before choosing tools or multi-agent orchestration."""
    attachments = attachments or []
    try:
        response = await generate_model_message([HumanMessage(content=_router_prompt(message, attachments, tool_catalog))])
        return _parse_decision(str(response.content), tool_catalog.names())
    except Exception as exc:
        return fallback_decision(
            message,
            attachments=attachments,
            available_tool_names=tool_catalog.names(),
            reason=f"模型路由不可用，使用本地规则：{exc}",
        )


def fallback_decision(
    message: str,
    *,
    attachments: list[InputAttachment] | None = None,
    available_tool_names: list[str] | None = None,
    reason: str = "使用本地规则路由。",
) -> ModelRouteDecision:
    attachments = attachments or []
    available_tool_names = available_tool_names or []
    normalized = message.strip().lower()
    has_image = any(attachment.kind == "image" for attachment in attachments)

    if has_image and _contains_any(normalized, ("反推", "提示词", "prompt", "midjourney", "stable diffusion")):
        return ModelRouteDecision(
            path="simple_chat",
            intent="image_prompt_reverse",
            worker="vision_worker",
            tool_names=[],
            needs_memory=False,
            needs_knowledge=False,
            confidence=0.82,
            reason="图片反推提示词只需要视觉理解，保持单轮快路径。",
        )

    if has_image and _contains_any(normalized, ("p图", "修图", "改成", "换成", "去掉", "替换", "风格化")):
        return ModelRouteDecision(
            path="direct_tool",
            intent="image_edit",
            worker="image_worker",
            tool_names=[name for name in ("edit_image",) if name in available_tool_names],
            needs_memory=_asks_for_memory(normalized),
            needs_knowledge=False,
            confidence=0.76,
            reason="图片编辑应由单个图片工具处理，避免进入多 agent 长链路。",
        )

    route = classify_task_route(
        message,
        file_ids=[attachment.file_id for attachment in attachments],
        available_tool_names=available_tool_names,
    )
    tool_names = _select_tools_for_route(route.path, route.domains, available_tool_names)
    return ModelRouteDecision(
        path=route.path,
        intent=_intent_from_domains(route.domains),
        worker=_worker_from_domains(route.domains),
        tool_names=tool_names,
        needs_memory=_asks_for_memory(normalized),
        needs_knowledge=_asks_for_knowledge(normalized) or "research" in route.domains,
        confidence=0.65 if route.path == "multi_agent" else 0.72,
        reason=reason if reason != "使用本地规则路由。" else route.reason,
    )


def _router_prompt(message: str, attachments: list[InputAttachment], tool_catalog: ToolCatalog) -> str:
    payload = {
        "user_message": message,
        "attachments": [
            {
                "file_id": attachment.file_id,
                "filename": attachment.filename,
                "mime_type": attachment.mime_type,
                "kind": attachment.kind,
                "size_bytes": attachment.size_bytes,
            }
            for attachment in attachments
        ],
        "tools": tool_catalog.describe_for_planner(),
    }
    return (
        "你是一个低延迟 agent 路由器，只做一次决策，不执行任务。\n"
        "目标：优先选择最短可行路径，避免不必要的多 agent 和记忆检索。\n"
        "路径规则：\n"
        "- simple_chat：普通回答、视觉理解、图片反推提示词、无需工具的任务。\n"
        "- direct_tool：单个明确工具可以完成的任务。\n"
        "- multi_agent：只有跨领域、多步骤、需要规划/执行/校验时才使用。\n"
        "记忆规则：只有用户明确提到偏好、习惯、以前、记住、我的信息，或任务确实依赖历史时，needs_memory 才为 true。\n"
        "知识规则：只有需要项目知识库/资料检索时，needs_knowledge 才为 true。\n"
        "只返回 JSON，不要 Markdown。字段为：path,intent,worker,tool_names,needs_memory,needs_knowledge,confidence,reason。\n\n"
        f"输入：{json.dumps(payload, ensure_ascii=False)}"
    )


def _parse_decision(content: str, available_tool_names: list[str]) -> ModelRouteDecision:
    data = _extract_json_object(content)
    path = data.get("path")
    if path not in {"simple_chat", "direct_tool", "multi_agent"}:
        raise ValueError("invalid route path")

    worker = data.get("worker")
    if worker not in {
        "general_worker",
        "vision_worker",
        "image_worker",
        "document_worker",
        "media_worker",
        "research_worker",
    }:
        worker = "general_worker"

    tool_names = [
        str(name)
        for name in data.get("tool_names", [])
        if isinstance(name, str) and name in set(available_tool_names)
    ]
    confidence = float(data.get("confidence", 0.5))
    return ModelRouteDecision(
        path=path,
        intent=str(data.get("intent") or "general_chat"),
        worker=worker,
        tool_names=tool_names,
        needs_memory=bool(data.get("needs_memory", False)),
        needs_knowledge=bool(data.get("needs_knowledge", False)),
        confidence=max(0.0, min(confidence, 1.0)),
        reason=str(data.get("reason") or "模型路由决策。"),
    )


def _extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("router response is not json")
    parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("router response must be a json object")
    return parsed


def _select_tools_for_route(path: TaskPath, domains: list[str], available_tool_names: list[str]) -> list[str]:
    if path == "simple_chat":
        return []
    if not domains:
        return []
    domain_tool_names = {
        "document": {
            "convert_uploaded_file",
            "ingest_uploaded_files_to_knowledge",
            "word_create",
            "word_read",
            "word_format",
            "word_edit_text",
            "pdf_create",
            "pdf_read",
        },
        "spreadsheet": {"excel_create", "excel_read", "excel_calculate", "excel_format_table"},
        "image": {"generate_image", "edit_image"},
        "media": {"parse_social_media_link"},
        "research": {"web_search", "get_current_weather"},
    }
    selected: list[str] = []
    available = set(available_tool_names)
    for domain in domains:
        for tool_name in domain_tool_names.get(domain, set()):
            if tool_name in available:
                selected.append(tool_name)
    return list(dict.fromkeys(selected))


def _intent_from_domains(domains: list[str]) -> str:
    if not domains:
        return "general_chat"
    if "image" in domains:
        return "image_task"
    if "media" in domains:
        return "media_parse"
    if "spreadsheet" in domains:
        return "spreadsheet_task"
    if "document" in domains:
        return "document_task"
    if "research" in domains:
        return "research_task"
    return "general_chat"


def _worker_from_domains(domains: list[str]) -> WorkerName:
    if "image" in domains:
        return "image_worker"
    if "media" in domains:
        return "media_worker"
    if "document" in domains or "spreadsheet" in domains:
        return "document_worker"
    if "research" in domains:
        return "research_worker"
    return "general_worker"


def _asks_for_memory(message: str) -> bool:
    return _contains_any(message, ("记住", "偏好", "习惯", "上次", "以前", "我的", "长期记忆"))


def _asks_for_knowledge(message: str) -> bool:
    return _contains_any(message, ("知识库", "资料库", "项目资料", "检索", "查询资料", "查资料"))


def _contains_any(message: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in message for keyword in keywords)
