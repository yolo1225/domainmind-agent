"""Runtime-editable model gateway configuration.

Model settings are seeded from ``.env`` at startup, then overridden by a single
row in the ``model_configs`` table. The database row is the runtime source of
truth: it is loaded on startup and applied live on save, so the running service
never needs ``.env`` to change. ``.env`` stays a host-owned, human-editable
fallback; a separate host-side script (``scripts/sync-model-env.ps1``) exports
the effective config back into it when needed.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import ModelConfig

logger = logging.getLogger(__name__)

CONFIG_ROW_KEY = "default"

# The "most common" model settings exposed by the visual config page.
EDITABLE_KEYS = (
    "openai_api_base",
    "primary_llm_model",
    "primary_review_model",
    "secondary_review_model",
    "embedding_model",
)

# Field name -> .env key, in the order the host sync script writes them.
ENV_KEY_FOR = {
    "openai_api_base": "OPENAI_API_BASE",
    "openai_api_key": "OPENAI_API_KEY",
    "primary_llm_model": "PRIMARY_LLM_MODEL",
    "primary_review_model": "PRIMARY_REVIEW_MODEL",
    "secondary_review_model": "SECONDARY_REVIEW_MODEL",
    "embedding_model": "EMBEDDING_MODEL",
}


# --------------------------------------------------------------------------- #
# Encryption
# --------------------------------------------------------------------------- #

def _fernet() -> Fernet:
    """Derive a stable Fernet key from the JWT secret (never stored anywhere)."""
    digest = hashlib.sha256(settings.jwt_secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_api_key(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(value: str) -> str | None:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.warning("model config API key could not be decrypted; ignoring persisted key")
        return None


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #

def get_row(db: Session) -> ModelConfig | None:
    return db.get(ModelConfig, CONFIG_ROW_KEY)


def _apply(config: dict[str, Any], api_key_value: str | None, *, clear_key: bool = False) -> None:
    """Apply overrides to the runtime settings singleton (read at call time)."""
    for key in EDITABLE_KEYS:
        value = _strip(config.get(key))
        # An empty database field means "use the .env fallback", not "erase it".
        if value:
            setattr(settings, key, value)
    if clear_key:
        settings.openai_api_key = None
    elif api_key_value:
        settings.openai_api_key = api_key_value


def load_from_db(db: Session) -> None:
    row = get_row(db)
    if row is None:
        return
    decrypted = decrypt_api_key(row.api_key_encrypted) if row.api_key_encrypted else None
    _apply(row.config_json or {}, decrypted)


def reload_from_db() -> None:
    """Load persisted overrides into the runtime settings singleton.

    Graceful by design: on a fresh volume the table may not exist until the
    first ``alembic upgrade head`` runs, so any failure is logged and skipped.
    """
    try:
        with SessionLocal() as db:
            load_from_db(db)
    except Exception:
        logger.warning("model config reload skipped; database unavailable", exc_info=True)


def _strip(value: str | None) -> str:
    return value.strip() if isinstance(value, str) else ""


def save_config(
    db: Session,
    *,
    openai_api_base: str,
    primary_llm_model: str,
    primary_review_model: str,
    secondary_review_model: str,
    embedding_model: str,
    openai_api_key: str | None = None,
    clear_openai_api_key: bool = False,
) -> None:
    config = {
        "openai_api_base": _strip(openai_api_base),
        "primary_llm_model": _strip(primary_llm_model),
        "primary_review_model": _strip(primary_review_model),
        "secondary_review_model": _strip(secondary_review_model),
        "embedding_model": _strip(embedding_model),
    }
    row = get_row(db)
    if row is None:
        row = ModelConfig(key=CONFIG_ROW_KEY, config_json={})
        db.add(row)
    row.config_json = config
    if clear_openai_api_key:
        row.api_key_encrypted = None
    elif openai_api_key and openai_api_key.strip():
        row.api_key_encrypted = encrypt_api_key(openai_api_key.strip())
    db.commit()

    decrypted = decrypt_api_key(row.api_key_encrypted) if row.api_key_encrypted else None
    _apply(config, decrypted, clear_key=clear_openai_api_key)


def effective_config() -> dict[str, Any]:
    return {
        "openai_api_base": settings.openai_api_base or "",
        "openai_api_key_set": bool(settings.openai_api_key),
        "primary_llm_model": settings.primary_llm_model or "",
        "primary_review_model": settings.primary_review_model or "",
        "secondary_review_model": settings.secondary_review_model or "",
        "embedding_model": settings.embedding_model or "",
    }


def export_env_lines() -> list[str]:
    """Return ``KEY=value`` lines for the host-side ``.env`` sync script."""
    return [
        f"{env_key}={getattr(settings, field) or ''}"
        for field, env_key in ENV_KEY_FOR.items()
    ]


# --------------------------------------------------------------------------- #
# Connection test
# --------------------------------------------------------------------------- #

def test_connection(
    *,
    openai_api_base: str = "",
    primary_llm_model: str = "",
    openai_api_key: str | None = None,
    **_unused: Any,
) -> dict[str, Any]:
    """Verify the (possibly unsaved) form values with a one-token chat call."""
    base = _strip(openai_api_base) or (settings.openai_api_base or "")
    key = (_strip(openai_api_key) if openai_api_key else "") or (settings.openai_api_key or "")
    model = _strip(primary_llm_model) or (settings.primary_llm_model or "")
    if not base:
        return {"ok": False, "message": "请先填写 API 地址"}
    if not key:
        return {"ok": False, "message": "请先填写 API Key"}
    if not model:
        return {"ok": False, "message": "请先填写主生成模型名"}
    try:
        client = OpenAI(api_key=key, base_url=base, timeout=8, max_retries=0)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        sample = (response.choices[0].message.content or "").strip()
        return {"ok": True, "message": f"连接成功（模型 {model}）", "sample": sample[:40]}
    except Exception as exc:
        logger.warning(
            "model connection test failed model=%s error_type=%s",
            model,
            type(exc).__name__,
        )
        code, message = _classify_connection_error(exc)
        return {"ok": False, "code": code, "message": message}


def _classify_connection_error(exc: Exception) -> tuple[str, str]:
    """Turn a provider exception into a stable code and an actionable hint."""
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return "auth", "API Key 无效或无权限，请检查密钥是否正确、是否过期"
    if isinstance(exc, NotFoundError):
        return "not_found", "模型名不存在或 API 地址路径不对（可能缺少 /v1，或模型名拼写错误）"
    if isinstance(exc, RateLimitError):
        return "rate_limit", "触发限流或账户额度不足，请稍后再试"
    if isinstance(exc, APITimeoutError):
        return "timeout", "连接超时，请检查网络或 API 地址是否可达"
    if isinstance(exc, APIConnectionError):
        return "connection", "无法连接到 API 地址，请确认地址正确且网络可达"
    if isinstance(exc, BadRequestError):
        return "bad_request", "请求被拒绝，通常是模型名错误或该参数不被服务支持"
    if isinstance(exc, InternalServerError):
        return "server_error", "模型服务端出错，请稍后再试"
    status = getattr(exc, "status_code", None)
    if status is not None:
        return "http_error", f"服务返回 HTTP {status}，请检查 API 地址、模型名与密钥"
    return "unknown", f"连接失败：{type(exc).__name__}"
