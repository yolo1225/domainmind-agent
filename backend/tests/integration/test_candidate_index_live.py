from __future__ import annotations

import os
import pytest

from app.core.config import Settings
from app.core.db import SessionLocal
from app.rag.candidate_index import CandidateIndexBuilder
from app.rag.candidate_manifest import CandidateManifestStore
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.rag.vector_store import VectorStore


@pytest.mark.live
def test_live_candidate_index_builds_real_cosine_collection() -> None:
    if os.getenv("RUN_LIVE_EMBEDDING_TESTS", "").lower() != "true":
        pytest.skip("set RUN_LIVE_EMBEDDING_TESTS=true to enable paid candidate indexing")

    live_settings = Settings()
    provider = OpenAICompatibleEmbeddingProvider(
        base_url=live_settings.openai_api_base,
        api_key=live_settings.openai_api_key,
        model=live_settings.embedding_model,
        timeout_seconds=live_settings.llm_timeout_seconds,
    )
    client = VectorStore().client
    store = CandidateManifestStore()
    with SessionLocal() as db:
        result = CandidateIndexBuilder(
            db=db,
            chroma_client=client,
            embedding_provider=provider,
            manifest_store=store,
        ).build(domain_code="ai_app_dev", reset=True)

    manifest = store.load(
        "ai_app_dev", collection_exists=lambda name: bool(client.get_collection(name=name))
    )
    assert manifest is not None
    collection = client.get_collection(name=manifest.active_collection)
    assert result["indexed_items"] == 50
    assert result["embedding_dimensions"] > 0
    assert result["indexed_chunks"] >= result["indexed_items"]
    assert manifest.active_collection == result["active_collection"]
    assert manifest.embedding_model == provider.model_name
    assert manifest.embedding_dimensions == result["embedding_dimensions"]
    assert manifest.distance_metric == "cosine"
    assert collection.count() == result["indexed_chunks"]
