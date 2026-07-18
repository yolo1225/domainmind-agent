from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import settings


logger = logging.getLogger(__name__)
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
ResponseAdapter = Callable[[dict[str, Any]], dict[str, Any]]


class ModelGatewayError(RuntimeError):
    """Base error for safe model failures exposed to workers and health checks."""


class ModelConfigurationError(ModelGatewayError):
    pass


class ModelResponseError(ModelGatewayError):
    pass


class ModelCallError(ModelGatewayError):
    pass


class OpenAICompatibleGateway:
    """Central model gateway with bounded retry and JSON output validation."""

    RETRY_DELAYS = (1, 3, 5)

    def _client(self) -> OpenAI:
        if not settings.openai_api_key:
            raise ModelConfigurationError("OPENAI_API_KEY is not configured")
        return OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
            timeout=settings.llm_timeout_seconds,
        )

    def complete_json(
        self,
        *,
        model: str | None,
        system_prompt: str,
        payload: dict[str, Any],
        fixture_factory: Callable[[], dict[str, Any]] | None = None,
        response_model: type[ResponseModel] | None = None,
        response_adapter: ResponseAdapter | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started_at = time.perf_counter()
        if not model or not settings.openai_api_key:
            if (
                settings.app_env != "production"
                and settings.allow_fixture_llm
                and fixture_factory is not None
            ):
                result = fixture_factory()
                if response_adapter is not None:
                    result = response_adapter(result)
                return self._validate(result, response_model), {
                    "provider_mode": "fixture",
                    "model_name": model or "fixture-model",
                    "tokens_input": 0,
                    "tokens_output": 0,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                }
            raise ModelConfigurationError("model channel is not configured")

        last_error: Exception | None = None
        client = self._client()
        for attempt in range(1, len(self.RETRY_DELAYS) + 2):
            try:
                response = client.chat.completions.create(
                    model=model,
                    response_format={"type": "json_object"},
                    messages=[
                        {
                            "role": "system",
                            "content": f"Return a valid JSON object.\n\n{system_prompt}",
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                )
                content = response.choices[0].message.content or "{}"
                result = json.loads(content)
                if response_adapter is not None:
                    result = response_adapter(result)
                result = self._validate(result, response_model)
                usage = response.usage
                return result, {
                    "provider_mode": "live",
                    "model_name": model,
                    "tokens_input": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "tokens_output": int(getattr(usage, "completion_tokens", 0) or 0),
                    "attempt": attempt,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                }
            except (json.JSONDecodeError, ValidationError, ModelResponseError) as exc:
                last_error = ModelResponseError(f"model returned invalid structured output: {exc}")
                logger.warning(
                    "Model structured output validation failed model=%s attempt=%s error_type=%s",
                    model,
                    attempt,
                    type(exc).__name__,
                )
                if attempt <= len(self.RETRY_DELAYS):
                    time.sleep(self.RETRY_DELAYS[attempt - 1])
            except Exception as exc:  # provider exceptions vary across compatible APIs
                last_error = exc
                logger.warning(
                    "Model call failed model=%s attempt=%s error_type=%s",
                    model,
                    attempt,
                    type(exc).__name__,
                )
                if attempt <= len(self.RETRY_DELAYS):
                    time.sleep(self.RETRY_DELAYS[attempt - 1])
        if isinstance(last_error, ModelResponseError):
            raise last_error
        raise ModelCallError(f"model call failed after 3 retries: {last_error}")

    @staticmethod
    def _validate(
        result: dict[str, Any], response_model: type[ResponseModel] | None
    ) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise ModelResponseError("JSON response must be an object")
        if response_model is None:
            return result
        return response_model.model_validate(
            OpenAICompatibleGateway._normalize_common_shapes(result)
        ).model_dump()

    @staticmethod
    def _normalize_common_shapes(value: Any) -> Any:
        if isinstance(value, list):
            return [OpenAICompatibleGateway._normalize_common_shapes(item) for item in value]
        if isinstance(value, dict):
            normalized = {
                key: OpenAICompatibleGateway._normalize_common_shapes(item)
                for key, item in value.items()
            }
            if "source_ids" in normalized and isinstance(normalized["source_ids"], str):
                normalized["source_ids"] = [normalized["source_ids"]]
            return normalized
        return value

    def configuration_status(self) -> dict[str, Any]:
        generation_ready = bool(settings.primary_llm_model)
        primary_review_ready = bool(settings.primary_review_model)
        secondary_review_ready = bool(settings.secondary_review_model)
        review_models_distinct = bool(
            primary_review_ready
            and secondary_review_ready
            and settings.primary_review_model != settings.secondary_review_model
        )
        gateway_ready = bool(settings.openai_api_key)
        ready_for_live_demo = bool(
            gateway_ready
            and generation_ready
            and primary_review_ready
            and secondary_review_ready
            and review_models_distinct
            and not settings.allow_fixture_llm
        )
        return {
            "status": "ok" if ready_for_live_demo else "degraded",
            "model_gateway": {
                "configured": gateway_ready,
                "base_url_configured": bool(settings.openai_api_base),
            },
            "generation_model": {
                "configured": generation_ready,
                "model_name": settings.primary_llm_model,
            },
            "primary_review_model": {
                "configured": primary_review_ready,
                "model_name": settings.primary_review_model,
            },
            "secondary_review_model": {
                "configured": secondary_review_ready,
                "model_name": settings.secondary_review_model,
            },
            "review_models_distinct": review_models_distinct,
            "fixture_enabled": settings.allow_fixture_llm,
            "ready_for_live_demo": ready_for_live_demo,
        }


gateway = OpenAICompatibleGateway()
