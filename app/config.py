from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://agent:agent@localhost:5432/agent_memory"

    openai_api_key: str = ""
    openai_base_url: str | None = None
    openai_model: str = "gpt-5.5"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
