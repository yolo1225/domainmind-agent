from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", str(PROJECT_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        extra="ignore",
    )

    app_name: str = "Yunchuan Zhihui MVP"
    app_env: str = "local"
    debug: bool = True
    schema_version: str = "1.0"
    api_v1_prefix: str = "/api/v1"
    frontend_origin: str = "http://localhost:5173"

    database_url: str = Field(
        default="mysql+pymysql://yunchuan:yunchuan_dev@localhost:3306/yunchuan_zhihui"
    )
    chroma_host: str = "localhost"
    chroma_port: int = 8000

    openai_api_base: str | None = None
    openai_api_key: str | None = None
    primary_llm_model: str | None = None
    primary_review_model: str | None = None
    secondary_review_model: str | None = None
    embedding_model: str | None = None
    llm_timeout_seconds: int = 30
    allow_fixture_llm: bool = False
    review_rule_version: str = "review-v1"

    log_level: str = "INFO"
    enable_full_debug_payloads: bool = False

@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
