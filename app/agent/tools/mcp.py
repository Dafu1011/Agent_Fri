from typing import Any


async def load_mcp_tools_from_config(
    server_config: dict[str, Any] | None,
) -> list[Any]:
    if not server_config:
        return []
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        return []

    try:
        client = MultiServerMCPClient(server_config)
        return await client.get_tools()
    except Exception:
        return []
