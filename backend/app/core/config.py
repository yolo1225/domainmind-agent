from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    jwt_secret_key: str = "local-development-secret-change-me"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = False
    redis_url: str = "redis://localhost:6379/0"
    initial_admin_username: str = "admin"
    initial_admin_password: str | None = None
    initial_admin_display_name: str = "系统管理员"

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
    primary_review_fallback_model: str | None = None
    secondary_review_fallback_model: str | None = None
    embedding_model: str | None = None
    llm_timeout_seconds: int = 30
    # OpenAI-compatible providers consistently support json_object. A true
    # json_schema request also requires a provider-specific schema payload and
    # must not be enabled by changing only the response type string.
    llm_json_schema_mode: Literal["json_object", "json_schema"] = "json_object"
    generation_max_output_tokens: int = 4000
    graded_quiz_max_output_tokens: int = 6000
    review_max_output_tokens: int = 3000
    review_timeout_seconds: int = 45
    review_task_timeout_seconds: int = 150
    review_batch_target_input_tokens: int = 4200
    review_batch_hard_input_tokens: int = 5000
    review_batch_output_tokens: int = 1400
    review_batch_max_claims: int = 12
    generation_model_concurrency: int = 3
    review_model_concurrency: int = 4
    allow_fixture_llm: bool = False
    enable_evaluation_overrides: bool = False
    enable_evaluation_runner: bool = False
    enable_knowledge_import_models: bool = True
    knowledge_import_model_concurrency: int = 4
    knowledge_import_generation_concurrency: int = 4
    knowledge_import_review_concurrency: int = 3
    knowledge_import_batch_target_tokens: int = 8000
    knowledge_import_batch_lease_seconds: int = 120
    knowledge_import_heartbeat_seconds: int = 30
    review_rule_version: str = "review-v5-claim-policy"

    log_level: str = "INFO"
    enable_full_debug_payloads: bool = False

    def validate_auth_config(self) -> None:
        if self.app_env not in {"local", "test"} and (
            self.jwt_secret_key == "local-development-secret-change-me"
            or len(self.jwt_secret_key.encode("utf-8")) < 32
        ):
            raise RuntimeError("JWT_SECRET_KEY must be a non-default secret of at least 32 bytes")

@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
