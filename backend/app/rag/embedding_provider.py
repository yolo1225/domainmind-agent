from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from typing import Any, Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from app.core.config import settings


logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingProviderError(RuntimeError):
    """Base error for safe embedding failures."""


class EmbeddingConfigurationError(EmbeddingProviderError):
    pass


class EmbeddingRequestError(EmbeddingProviderError):
    pass


class EmbeddingResponseError(EmbeddingProviderError):
    pass


class OpenAICompatibleEmbeddingProvider:
    BATCH_SIZE = 16
    RETRY_DELAYS = (1, 3, 5)

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = settings.openai_api_base if base_url is None else base_url
        self._api_key = settings.openai_api_key if api_key is None else api_key
        self._model_name = settings.embedding_model if model is None else model
        self._timeout_seconds = (
            settings.llm_timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        self._sleep = sleep
        self._validate_configuration()
        self._client = client or OpenAI(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=self._timeout_seconds,
            max_retries=0,
        )

    @property
    def model_name(self) -> str:
        return str(self._model_name)

    def _validate_configuration(self) -> None:
        missing = [
            name
            for name, value in (
                ("OPENAI_API_BASE", self._base_url),
                ("OPENAI_API_KEY", self._api_key),
                ("EMBEDDING_MODEL", self._model_name),
            )
            if not isinstance(value, str) or not value.strip()
        ]
        if missing:
            raise EmbeddingConfigurationError(
                f"embedding provider configuration is missing: {', '.join(missing)}"
            )
        if not isinstance(self._timeout_seconds, int) or self._timeout_seconds <= 0:
            raise EmbeddingConfigurationError("LLM_TIMEOUT_SECONDS must be a positive integer")
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        invalid_positions = [
            index
            for index, text in enumerate(texts)
            if not isinstance(text, str) or not text.strip()
        ]
        if invalid_positions:
            positions = ", ".join(str(index) for index in invalid_positions)
            raise EmbeddingRequestError(
                f"embedding input contains blank text at positions: {positions}"
            )

        vectors: list[list[float]] = []
        dimensions: int | None = None
        started = time.perf_counter()
        batches = [
            texts[index : index + self.BATCH_SIZE]
            for index in range(0, len(texts), self.BATCH_SIZE)
        ]
        for batch_number, batch in enumerate(batches, start=1):
            batch_vectors = self._embed_batch(batch, batch_number=batch_number)
            batch_dimensions = len(batch_vectors[0])
            if dimensions is None:
                dimensions = batch_dimensions
            elif dimensions != batch_dimensions:
                raise EmbeddingResponseError(
                    "embedding dimensions differ across batches: "
                    f"expected {dimensions}, received {batch_dimensions}"
                )
            vectors.extend(batch_vectors)

        if len(vectors) != len(texts):
            raise EmbeddingResponseError(
                f"embedding count mismatch: expected {len(texts)}, received {len(vectors)}"
            )
        logger.info(
            "Embedding request completed model=%s text_count=%s batch_count=%s "
            "dimensions=%s duration_ms=%s",
            self.model_name,
            len(texts),
            len(batches),
            dimensions,
            round((time.perf_counter() - started) * 1000),
        )
        return vectors
    def _embed_batch(self, batch: list[str], *, batch_number: int) -> list[list[float]]:
        last_error_type = "unknown"
        for attempt in range(1, len(self.RETRY_DELAYS) + 2):
            try:
                response = self._client.embeddings.create(model=self.model_name, input=batch)
                return self._validate_response(response, expected_count=len(batch))
            except EmbeddingResponseError:
                raise
            except Exception as exc:  # compatible providers expose different exception subclasses
                last_error_type = type(exc).__name__
                status_code = getattr(exc, "status_code", None)
                retryable = self._is_retryable(exc)
                logger.warning(
                    "Embedding request failed model=%s batch=%s attempt=%s "
                    "error_type=%s status_code=%s retryable=%s",
                    self.model_name,
                    batch_number,
                    attempt,
                    last_error_type,
                    status_code,
                    retryable,
                )
                if not retryable:
                    raise EmbeddingRequestError(
                        "embedding request failed with a non-retryable provider error: "
                        f"{last_error_type}"
                    ) from exc
                if attempt > len(self.RETRY_DELAYS):
                    break
                self._sleep(self.RETRY_DELAYS[attempt - 1])
        raise EmbeddingRequestError(
            f"embedding request failed after 3 retries: {last_error_type}"
        )

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError)):
            return True
        status_code = getattr(exc, "status_code", None)
        if isinstance(exc, APIStatusError) or isinstance(status_code, int):
            return status_code == 429 or status_code >= 500
        return False
    @staticmethod
    def _validate_response(response: Any, *, expected_count: int) -> list[list[float]]:
        data = list(getattr(response, "data", []) or [])
        if len(data) != expected_count:
            raise EmbeddingResponseError(
                f"embedding response count mismatch: expected {expected_count}, received {len(data)}"
            )
        indexes = [getattr(item, "index", None) for item in data]
        if any(not isinstance(index, int) or isinstance(index, bool) for index in indexes):
            raise EmbeddingResponseError("embedding response contains an invalid index")
        if sorted(indexes) != list(range(expected_count)):
            raise EmbeddingResponseError("embedding response indexes are missing or duplicated")

        ordered = sorted(data, key=lambda item: int(item.index))
        vectors: list[list[float]] = []
        dimensions: int | None = None
        for item in ordered:
            raw_vector = getattr(item, "embedding", None)
            if not isinstance(raw_vector, (list, tuple)) or not raw_vector:
                raise EmbeddingResponseError("embedding response contains an empty vector")
            try:
                vector = [float(value) for value in raw_vector]
            except (TypeError, ValueError) as exc:
                raise EmbeddingResponseError(
                    "embedding response contains a non-numeric vector value"
                ) from exc
            if not all(math.isfinite(value) for value in vector):
                raise EmbeddingResponseError("embedding response contains a non-finite value")
            if dimensions is None:
                dimensions = len(vector)
            elif len(vector) != dimensions:
                raise EmbeddingResponseError("embedding dimensions differ within a batch")
            vectors.append(vector)
        return vectors
