from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "info"
    database_url: str = "postgresql+asyncpg://chatbot:chatbot@127.0.0.1:5433/chatbot"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    chat_base_url: str = "http://127.0.0.1:8000"
    chat_user_id: str = "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
