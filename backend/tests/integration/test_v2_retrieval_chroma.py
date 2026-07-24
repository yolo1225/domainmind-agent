from __future__ import annotations

from pathlib import Path

import chromadb
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.contracts import RetrieveKnowledgeInput
from app.models import Base, KnowledgeItem
from app.rag.candidate_manifest import (
    DISTANCE_METRIC,
    MANIFEST_SCHEMA_VERSION,
    CandidateIndexManifest,
    CandidateManifestStore,
    compute_index_version,
)
from app.rag.v2_retrieval import V2CandidateRetriever


class DeterministicProvider:
    model_name = "integration-embedding"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


def _input() -> RetrieveKnowledgeInput:
    return RetrieveKnowledgeInput.model_validate(
        {
            "task_id": "v2-integration",
            "context": {
                "task_id": "v2-integration",
                "session_id": "v2-integration",
                "trigger_type": "initial_generation",
                "execution_mode": "auto",
                "learner_id": "learner-v2",
                "profile_id": "profile-v2",
                "domain_code": "ai_app_dev",
                "resource_types": ["lecture"],
                "learning_goal": "RAG evidence retrieval",
            },
            "profile": {
                "profile_id": "profile-v2",
                "profile_version": 1,
                "profile_type": "beginner",
                "ability_scores": {"theory": 30, "practice": 30, "problem_solving": 30, "knowledge_breadth": 30, "learning_speed": 30},
            },
            "retrieval_plan": {
                "strategy": "consolidation",
                "target_difficulty": 2,
                "resource_types": ["lecture"],
                "priority_knowledge_ids": ["rag-basics"],
                "query_terms": ["RAG", "evidence"],
                "n_results": 8,
            },
            "purpose": "consolidation_practice",
        }
    )


def test_v2_retrieval_uses_local_chroma_candidate_collection(tmp_path: Path) -> None:
    source_version = "sha256:" + "2" * 64
    index_version = compute_index_version(
        domain_code="ai_app_dev",
        source_data_version=source_version,
        embedding_model="integration-embedding",
        embedding_dimensions=3,
        distance_metric=DISTANCE_METRIC,
        chunker_version="candidate-heading-v2",
    )
    collection_name = "knowledge_ai_app_dev_candidate_integration"
    client = chromadb.Client()
    collection = client.create_collection(
        name=collection_name,
        configuration={"hnsw": {"space": "cosine"}},
        metadata={
            "domain_code": "ai_app_dev",
            "embedding_model": "integration-embedding",
            "embedding_dimensions": 3,
            "distance_metric": "cosine",
            "index_version": index_version,
            "chunker_version": "candidate-heading-v2",
        },
        embedding_function=None,
    )
    collection.add(
        ids=["rag-basics::chunk::0"],
        documents=["RAG evidence must retain traceable sources."],
        embeddings=[[1.0, 0.0, 0.0]],
        metadatas=[
            {
                "domain_code": "ai_app_dev",
                "knowledge_id": "rag-basics",
                "name": "RAG basics",
                "category": "RAG",
                "difficulty": 2,
                "source_title": "Official RAG documentation",
                "source_url": "https://example.com/rag",
                "license_note": "Official documentation summary",
                "chunk_index": 0,
                "embedding_model": "integration-embedding",
                "embedding_dimensions": 3,
            }
        ],
    )
    store = CandidateManifestStore(root=tmp_path)
    store.write(
        CandidateIndexManifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            active_collection=collection_name,
            previous_collection=None,
            domain_code="ai_app_dev",
            embedding_model="integration-embedding",
            embedding_dimensions=3,
            distance_metric=DISTANCE_METRIC,
            chunker_version="candidate-heading-v2",
            index_version=index_version,
            source_data_version=source_version,
            last_successful_sync_at="2026-07-24T12:00:00+00:00",
            indexed_item_count=1,
            indexed_chunk_count=1,
        )
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add(
            KnowledgeItem(
                public_id="rag-basics",
                domain_code="ai_app_dev",
                name="RAG basics",
                category="RAG",
                difficulty=2,
                tags_json=[],
                content_md="RAG content",
                source_title="Official RAG documentation",
                source_url="https://example.com/rag",
                license_note="Official documentation summary",
            )
        )
        db.commit()
        result = V2CandidateRetriever(
            db=db,
            chroma_client=client,
            embedding_provider=DeterministicProvider(),
            manifest_store=store,
        ).execute(_input())

    assert result.covered_knowledge_ids == ["rag-basics"]
    assert result.chunks[0].source.source_ref_id == "rag-basics::chunk::0"
    assert result.chunks[0].matched_by.value == "priority"
