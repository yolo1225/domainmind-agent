from __future__ import annotations

import math
import os

import pytest

from app.core.config import Settings
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider


@pytest.mark.live
def test_live_embedding_provider_returns_consistent_vectors() -> None:
    if os.getenv("RUN_LIVE_EMBEDDING_TESTS", "").lower() != "true":
        pytest.skip("set RUN_LIVE_EMBEDDING_TESTS=true to enable paid live embedding calls")

    live_settings = Settings()
    provider = OpenAICompatibleEmbeddingProvider(
        base_url=live_settings.openai_api_base,
        api_key=live_settings.openai_api_key,
        model=live_settings.embedding_model,
        timeout_seconds=live_settings.llm_timeout_seconds,
    )
    vectors = provider.embed_texts(
        [
            "人工智能应用开发需要可验证的数据与模型流程。",
            "检索增强生成应保留知识来源。",
        ]
    )

    assert len(vectors) == 2
    assert len(vectors[0]) > 0
    assert len(vectors[0]) == len(vectors[1])
    assert all(math.isfinite(value) for vector in vectors for value in vector)
