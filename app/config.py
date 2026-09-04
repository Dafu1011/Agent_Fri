import json
from pathlib import Path
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
    storage_dir: str = "runtime"

    media_cache_ttl_seconds: int = 86400
    media_request_timeout_seconds: int = 8
    media_parse_concurrency_limit: int = 5
    media_douyin_parse_concurrency_limit: int = 5
    media_xhs_parse_concurrency_limit: int = 5
    media_kuaishou_parse_concurrency_limit: int = 5
    media_download_timeout_seconds: int = 120
    media_max_download_mb: int = 500
    media_preview_transcode_enabled: bool = True
    media_ffmpeg_path: str = ""
    media_parse_lock_ttl_seconds: int = 30
    media_preview_lock_ttl_seconds: int = 300
    media_preview_concurrency_limit: int = 5
    media_preview_cache_ttl_seconds: int = 86400
    media_preview_cache_max_mb: int = 2048
    media_cookie_pool_path: str = ""
    media_cookie_failure_cooldown_seconds: int = 300
    media_douyin_user_agent: str = ""
    media_xhs_user_agent: str = ""
    media_kuaishou_user_agent: str = ""

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir)

    def __getattr__(self, name: str) -> Any:
        lower_name = name.lower()
        if lower_name != name and hasattr(self, lower_name):
            return getattr(self, lower_name)
        raise AttributeError(name)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()


def get_settings() -> Settings:
    return settings


def parse_mcp_servers_json(value: str) -> dict[str, Any]:
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
