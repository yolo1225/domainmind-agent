from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app.rag.embedding_provider import (
    EmbeddingConfigurationError,
    EmbeddingRequestError,
    EmbeddingResponseError,
    OpenAICompatibleEmbeddingProvider,
)


def _response(vectors: list[list[float]], indexes: list[int] | None = None) -> Any:
    indexes = indexes if indexes is not None else list(range(len(vectors)))
    return SimpleNamespace(
        data=[
            SimpleNamespace(index=index, embedding=vector)
            for index, vector in zip(indexes, vectors, strict=True)
        ]
    )


class FakeEmbeddings:
    def __init__(self, outcomes: list[Any] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[dict[str, Any]] = []

    def create(self, *, model: str, input: list[str]) -> Any:
        self.calls.append({"model": model, "input": list(input)})
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return _response([[float(index), 1.0] for index in range(len(input))])


class FakeClient:
    def __init__(self, outcomes: list[Any] | None = None) -> None:
        self.embeddings = FakeEmbeddings(outcomes)


class ProviderStatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"provider status {status_code}")


def _provider(
    client: FakeClient, *, sleeps: list[float] | None = None
) -> OpenAICompatibleEmbeddingProvider:
    return OpenAICompatibleEmbeddingProvider(
        base_url="https://provider.example/v1",
        api_key="test-secret-key",
        model="test-embedding-model",
        timeout_seconds=30,
        client=client,
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


def test_missing_live_configuration_is_rejected() -> None:
    with pytest.raises(EmbeddingConfigurationError, match="OPENAI_API_BASE"):
        OpenAICompatibleEmbeddingProvider(
            base_url="", api_key="", model="", timeout_seconds=30, client=FakeClient()
        )


def test_empty_input_does_not_call_provider() -> None:
    client = FakeClient()
    assert _provider(client).embed_texts([]) == []
    assert client.embeddings.calls == []


def test_blank_input_reports_positions_without_calling_provider() -> None:
    client = FakeClient()
    with pytest.raises(EmbeddingRequestError, match="positions: 1, 2"):
        _provider(client).embed_texts(["valid", " ", ""])
    assert client.embeddings.calls == []


def test_thirty_three_texts_are_split_into_16_16_and_1() -> None:
    client = FakeClient()
    vectors = _provider(client).embed_texts([f"text-{index}" for index in range(33)])
    assert len(vectors) == 33
    assert [len(call["input"]) for call in client.embeddings.calls] == [16, 16, 1]


def test_response_is_restored_to_input_index_order() -> None:
    client = FakeClient([_response([[20.0, 2.0], [10.0, 1.0]], indexes=[1, 0])])
    assert _provider(client).embed_texts(["first", "second"]) == [
        [10.0, 1.0],
        [20.0, 2.0],
    ]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_response([[1.0, 2.0]]), "count mismatch"),
        (_response([[1.0], [2.0]], indexes=[0, None]), "invalid index"),
        (_response([[1.0], [2.0]], indexes=[0, 0]), "indexes are missing or duplicated"),
        (_response([[1.0], []]), "empty vector"),
        (_response([[1.0], [2.0, 3.0]]), "dimensions differ within a batch"),
        (_response([[1.0], [float("nan")]]), "non-finite value"),
    ],
)
def test_invalid_provider_responses_fail_immediately(response: Any, message: str) -> None:
    client = FakeClient([response])
    with pytest.raises(EmbeddingResponseError, match=message):
        _provider(client).embed_texts(["first", "second"])
    assert len(client.embeddings.calls) == 1


def test_dimensions_must_match_across_batches() -> None:
    client = FakeClient(
        [
            _response([[1.0, 2.0] for _ in range(16)]),
            _response([[1.0, 2.0, 3.0] for _ in range(16)]),
        ]
    )
    with pytest.raises(EmbeddingResponseError, match="differ across batches"):
        _provider(client).embed_texts([f"text-{index}" for index in range(33)])


def test_retryable_failure_uses_configured_delay_then_succeeds() -> None:
    sleeps: list[float] = []
    client = FakeClient([ProviderStatusError(429), _response([[1.0, 2.0]])])
    assert _provider(client, sleeps=sleeps).embed_texts(["text"]) == [[1.0, 2.0]]
    assert sleeps == [1]
    assert len(client.embeddings.calls) == 2


def test_retry_stops_after_three_retries() -> None:
    sleeps: list[float] = []
    client = FakeClient([ProviderStatusError(503) for _ in range(4)])
    with pytest.raises(EmbeddingRequestError, match="after 3 retries"):
        _provider(client, sleeps=sleeps).embed_texts(["text"])
    assert sleeps == [1, 3, 5]
    assert len(client.embeddings.calls) == 4


def test_non_retryable_provider_failure_fails_immediately() -> None:
    sleeps: list[float] = []
    client = FakeClient([ProviderStatusError(401)])
    with pytest.raises(EmbeddingRequestError, match="non-retryable"):
        _provider(client, sleeps=sleeps).embed_texts(["text"])
    assert sleeps == []
    assert len(client.embeddings.calls) == 1


def test_logs_do_not_contain_input_secret_or_vectors(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeClient([ProviderStatusError(401)])
    sensitive_text = "private learner answer"
    with caplog.at_level(logging.INFO), pytest.raises(EmbeddingRequestError):
        _provider(client).embed_texts([sensitive_text])
    assert sensitive_text not in caplog.text
    assert "test-secret-key" not in caplog.text
    assert "[" not in caplog.text
