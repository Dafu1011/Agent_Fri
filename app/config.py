import json
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://agent:agent@localhost:5432/agent_memory"

    openai_api_key: str = ""
    openai_base_url: str | None = None
    openai_model: str = "gpt-5.5"
    openai_embedding_api_key: str = ""
    openai_embedding_base_url: str | None = None
    openai_embedding_model: str = "qwen3.7-text-embedding"
    openai_embedding_dimensions: int = 1536
    tavily_api_key: str = ""
    web_search_provider: str = "searxng"
    searxng_base_url: str = ""
    web_search_max_results: int = 5
    mcp_servers_json: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()


def parse_mcp_servers_json(value: str) -> dict[str, Any]:
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
