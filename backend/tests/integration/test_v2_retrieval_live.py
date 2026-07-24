from __future__ import annotations

import os

import pytest

from app.agents.v2_retrieval_agent import V2KnowledgeRetrievalAgent
from app.core.config import Settings
from app.rag.candidate_manifest import CandidateManifestStore
from app.rag.vector_store import VectorStore
from app.scripts.validate_rag_evaluation import load_evaluation_data, materialize_retrieve_input


@pytest.mark.live
def test_live_v2_retrieval_uses_active_candidate_manifest() -> None:
    if os.getenv("RUN_LIVE_EMBEDDING_TESTS", "").lower() != "true":
        pytest.skip("set RUN_LIVE_EMBEDDING_TESTS=true to enable paid V2 retrieval")
    settings = Settings()
    if not all((settings.openai_api_base, settings.openai_api_key, settings.embedding_model)):
        pytest.skip("live embedding configuration is incomplete")

    datasets, _ = load_evaluation_data()
    request = materialize_retrieve_input(datasets["development"][0], "ai_app_dev")
    client = VectorStore().client
    manifest = CandidateManifestStore().load(
        "ai_app_dev", collection_exists=lambda name: bool(client.get_collection(name=name))
    )
    assert manifest is not None

    with V2KnowledgeRetrievalAgent.production() as agent:
        result = agent.execute(request)

    assert result.task_id == request.task_id
    assert len(result.chunks) <= request.retrieval_plan.n_results
    assert all(chunk.source.source_ref_id == chunk.chunk_id for chunk in result.chunks)
    assert all(chunk.source.source_title and chunk.source.license_note for chunk in result.chunks)
    assert all(0 <= chunk.similarity <= 1 for chunk in result.chunks)
