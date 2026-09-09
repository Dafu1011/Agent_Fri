from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TaskPath = Literal["simple_chat", "direct_tool", "multi_agent"]


@dataclass(frozen=True)
class TaskRoute:
    path: TaskPath
    complexity: Literal["low", "medium", "high"]
    domains: list[str]
    reason: str


def classify_task_route(
    message: str,
    *,
    file_ids: list[str] | None = None,
    available_tool_names: list[str] | None = None,
) -> TaskRoute:
    normalized = message.strip().lower()
    tool_names = set(available_tool_names or [])
    domains = _infer_domains(normalized, tool_names)

    if _is_complex_task(normalized, domains):
        return TaskRoute(
            path="multi_agent",
            complexity="high",
            domains=domains,
            reason="任务包含多个步骤或跨工具域，需要规划、执行和校验。",
        )

    if file_ids and domains:
        return TaskRoute(
            path="direct_tool",
            complexity="medium",
            domains=domains,
            reason="任务带有文件输入且可由单个工具直接处理。",
        )

    return TaskRoute(
        path="simple_chat",
        complexity="low",
        domains=domains,
        reason="任务可以由普通聊天或单轮工具调用处理。",
    )


def _infer_domains(message: str, tool_names: set[str]) -> list[str]:
    domains: list[str] = []
    if any(keyword in message for keyword in ("word", "docx", "pdf", "文档", "合同", "总结")):
        domains.append("document")
    if any(keyword in message for keyword in ("excel", "xlsx", "表格", "利润", "计算")):
        domains.append("spreadsheet")
    if any(keyword in message for keyword in ("图片", "海报", "生成图", "画一张")):
        domains.append("image")
    if any(keyword in message for keyword in ("抖音", "快手", "小红书", "视频链接", "解析链接")):
        domains.append("media")
    if any(keyword in message for keyword in ("搜索", "查询", "查一下", "资料", "对比")) or "web_search" in tool_names:
        domains.append("research")
    return list(dict.fromkeys(domains))


def _is_complex_task(message: str, domains: list[str]) -> bool:
    multi_step_markers = ("然后", "并且", "再", "最后", "同时", "生成一份", "导出")
    action_count = sum(1 for marker in multi_step_markers if marker in message)
    return action_count >= 1 and (len(domains) >= 1 or "计算" in message)
