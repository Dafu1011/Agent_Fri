from typing import Any

from app.agent.tools.mcp import load_mcp_tools_from_config
from app.agent.tools.media import build_media_tools
from app.agent.tools.web import build_web_tools


def build_builtin_tools() -> list[Any]:
    """Return tools that are always available without optional integrations."""
    return [*build_web_tools(), *build_media_tools()]


def build_tools(extra_tools: list[Any] | None = None) -> list[Any]:
    tools = [*build_builtin_tools()]
    if extra_tools:
        tools.extend(extra_tools)
    return tools


async def build_runtime_tools(
    mcp_config: dict[str, Any] | None = None,
    extra_tools: list[Any] | None = None,
) -> list[Any]:
    tools = build_tools(extra_tools=extra_tools)
    tools.extend(await load_mcp_tools_from_config(mcp_config))
    return tools
