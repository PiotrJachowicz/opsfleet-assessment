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
    gemini_model: str = "gemini-3.8-flash"
    gemini_include_thoughts: bool = True
    gemini_thinking_level: str = "medium"
    gemini_max_retries: int = 5
    gemini_retry_initial_delay: float = 2.0
    gemini_retry_max_delay: float = 60.0
    gemini_retry_backoff: float = 2.0
    gemini_timeout_seconds: float = 120.0
    gcp_project: str = "ops-test-piotr"
    google_application_credentials: str = ""
    bq_dataset: str = "bigquery-public-data.thelook_ecommerce"
    bq_max_rows: int = 100
    bq_max_bytes_billed: int = 1_000_000_000
    bq_timeout_seconds: float = 60.0
    agent_recursion_limit: int = 25
    jwt_secret: str = "dev-jwt-secret-change-me"
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "opsfleet-chatbot"
    langsmith_endpoint: str = ""
    langsmith_dataset: str = "opsfleet-retail-agent-eval"


@lru_cache
def get_settings() -> Settings:
    return Settings()
