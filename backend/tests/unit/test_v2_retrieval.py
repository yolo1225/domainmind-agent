from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.contracts import RetrieveKnowledgeInput
from app.models import Base, KnowledgeItem, KnowledgeRelation
from app.rag.candidate_manifest import (
    DISTANCE_METRIC,
    MANIFEST_SCHEMA_VERSION,
    CandidateIndexManifest,
    CandidateManifestStore,
    compute_index_version,
)
from app.rag.v2_retrieval import V2CandidateRetriever, V2RetrievalError


class FakeProvider:
    model_name = "test-embedding"

    def __init__(self, vector: list[float] | None = None) -> None:
        self.vector = vector or [1.0, 0.0, 0.0]
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [list(self.vector) for _ in texts]


class FakeCollection:
    def __init__(self, name: str, records: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
        self.name = name
        self.records = {record["id"]: record for record in records}
        self.metadata = metadata

    def count(self) -> int:
        return len(self.records)

    def get(self, *, where=None, include=None) -> dict[str, Any]:
        records = list(self.records.values())
        if where:
            records = [
                record
                for record in records
                if all(record["metadata"].get(key) == value for key, value in where.items())
            ]
        records.sort(key=lambda record: record["id"])
        return {
            "ids": [record["id"] for record in records],
            "documents": [record["document"] for record in records],
            "metadatas": [record["metadata"] for record in records],
            "embeddings": [record["embedding"] for record in records],
        }

    def query(self, *, query_embeddings, n_results, include) -> dict[str, Any]:
        query = query_embeddings[0]
        ranked = sorted(
            self.records.values(),
            key=lambda record: (
                -sum(a * b for a, b in zip(query, record["embedding"], strict=True)),
                record["id"],
            ),
        )[:n_results]
        return {
            "ids": [[record["id"] for record in ranked]],
            "documents": [[record["document"] for record in ranked]],
            "metadatas": [[record["metadata"] for record in ranked]],
            "embeddings": [[record["embedding"] for record in ranked]],
            "distances": [[1 - sum(a * b for a, b in zip(query, record["embedding"], strict=True)) for record in ranked]],
        }


class FakeClient:
    def __init__(self, collection: FakeCollection) -> None:
        self.collection = collection

    def get_collection(self, *, name: str) -> FakeCollection:
        if name != self.collection.name:
            raise ValueError("missing collection")
        return self.collection


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _item(public_id: str, *, difficulty: int = 2) -> KnowledgeItem:
    return KnowledgeItem(
        public_id=public_id,
        domain_code="ai_app_dev",
        name=f"Name {public_id}",
        category="RAG",
        difficulty=difficulty,
        tags_json=[],
        content_md="content",
        source_title="Source",
        source_url="https://example.com",
        license_note="Official documentation",
    )


def _record(knowledge_id: str, index: int, vector: list[float], *, source=True) -> dict[str, Any]:
    return {
        "id": f"{knowledge_id}::chunk::{index}",
        "document": f"Document {knowledge_id} {index}",
        "embedding": vector,
        "metadata": {
            "domain_code": "ai_app_dev",
            "knowledge_id": knowledge_id,
            "name": f"Name {knowledge_id}",
            "category": "RAG",
            "difficulty": 2,
            "source_title": "Source" if source else "",
            "source_url": "https://example.com" if source else "",
            "license_note": "Official documentation" if source else "",
            "chunk_index": index,
            "embedding_model": "test-embedding",
            "embedding_dimensions": 3,
        },
    }


def _manifest_store(tmp_path: Path, records: list[dict[str, Any]]) -> tuple[CandidateManifestStore, dict[str, Any]]:
    source_version = "sha256:" + "1" * 64
    metadata = {
        "domain_code": "ai_app_dev",
        "embedding_model": "test-embedding",
        "embedding_dimensions": 3,
        "distance_metric": DISTANCE_METRIC,
        "chunker_version": "candidate-heading-v2",
    }
    index_version = compute_index_version(
        domain_code="ai_app_dev",
        source_data_version=source_version,
        embedding_model="test-embedding",
        embedding_dimensions=3,
        distance_metric=DISTANCE_METRIC,
        chunker_version="candidate-heading-v2",
    )
    name = "knowledge_ai_app_dev_candidate_test"
    metadata["index_version"] = index_version
    store = CandidateManifestStore(root=tmp_path)
    store.write(
        CandidateIndexManifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            active_collection=name,
            previous_collection=None,
            domain_code="ai_app_dev",
            embedding_model="test-embedding",
            embedding_dimensions=3,
            distance_metric=DISTANCE_METRIC,
            chunker_version="candidate-heading-v2",
            index_version=index_version,
            source_data_version=source_version,
            last_successful_sync_at="2026-07-24T12:00:00+00:00",
            indexed_item_count=len({record["metadata"]["knowledge_id"] for record in records}),
            indexed_chunk_count=len(records),
        )
    )
    return store, metadata


def _input(*, priority=None, prerequisite=None, revision=None, purpose="remedial_explanation", n_results=8) -> RetrieveKnowledgeInput:
    return RetrieveKnowledgeInput.model_validate(
        {
            "task_id": "task-v2-1",
            "context": {
                "task_id": "task-v2-1",
                "session_id": "session-v2-1",
                "trigger_type": "initial_generation",
                "execution_mode": "auto",
                "learner_id": "learner-v2",
                "profile_id": "profile-v2",
                "domain_code": "ai_app_dev",
                "resource_types": ["lecture"],
                "learning_goal": "Learn RAG retrieval",
            },
            "profile": {
                "profile_id": "profile-v2",
                "profile_version": 1,
                "profile_type": "beginner",
                "ability_scores": {"theory": 30, "practice": 30, "problem_solving": 30, "knowledge_breadth": 30, "learning_speed": 30},
                "weak_knowledge": [{"knowledge_id": "weak-1", "name": "Weak name", "category": "Weak category", "weakness_level": 4, "mastery_type": "unmastered", "reason": "diagnosis"}],
            },
            "retrieval_plan": {
                "strategy": "remedial",
                "target_difficulty": 2,
                "resource_types": ["lecture"],
                "priority_knowledge_ids": priority or [],
                "prerequisite_knowledge_ids": prerequisite or [],
                "query_terms": ["RAG", "retrieval"],
                "n_results": n_results,
            },
            "revision_plan": revision,
            "purpose": purpose,
        }
    )


def _retriever(tmp_path: Path, db, records, *, mode="full", vector=None) -> tuple[V2CandidateRetriever, FakeProvider]:
    store, metadata = _manifest_store(tmp_path, records)
    collection = FakeCollection("knowledge_ai_app_dev_candidate_test", records, metadata)
    provider = FakeProvider(vector)
    return V2CandidateRetriever(db=db, chroma_client=FakeClient(collection), embedding_provider=provider, manifest_store=store, mode=mode), provider


def test_v2_retrieval_combines_explicit_relation_and_semantic_with_real_cosine(tmp_path: Path) -> None:
    sessions = _session()
    records = [
        _record("priority", 0, [0.5, 0.5, 0.0]),
        _record("prerequisite", 0, [0.8, 0.2, 0.0]),
        _record("related", 0, [0.7, 0.0, 0.0]),
        _record("dependent", 0, [0.6, 0.0, 0.0]),
        _record("semantic", 0, [0.9, 0.0, 0.0]),
    ]
    with sessions() as db:
        priority, prerequisite, related, dependent, semantic = [_item(value) for value in ("priority", "prerequisite", "related", "dependent", "semantic")]
        db.add_all([priority, prerequisite, related, dependent, semantic])
        db.flush()
        db.add_all([
            KnowledgeRelation(source_item_id=prerequisite.id, target_item_id=priority.id, relation_type="prerequisite"),
            KnowledgeRelation(source_item_id=priority.id, target_item_id=dependent.id, relation_type="prerequisite"),
            KnowledgeRelation(source_item_id=priority.id, target_item_id=related.id, relation_type="related"),
        ])
        db.commit()
        retriever, provider = _retriever(tmp_path, db, records)
        result = retriever.execute(_input(priority=["priority"], prerequisite=["prerequisite"]))

    routes = {chunk.knowledge_id: chunk.matched_by.value for chunk in result.chunks}
    assert result.query_text == "Learn RAG retrieval RAG retrieval Weak name Weak category"
    assert routes["priority"] == "priority"
    assert routes["prerequisite"] == "prerequisite"
    assert routes["related"] == "related"
    assert routes["dependent"] == "dependent"
    assert result.chunks[0].similarity == pytest.approx(0.5)
    assert result.chunks[0].similarity != 1.0
    assert provider.calls == [[result.query_text]]
    assert set(result.covered_knowledge_ids).isdisjoint(result.missing_knowledge_ids)


def test_v2_retrieval_keeps_revision_query_and_reports_explicit_budget(tmp_path: Path) -> None:
    sessions = _session()
    records = [_record(value, 0, [1.0, 0.0, 0.0]) for value in ("a", "b", "c")]
    with sessions() as db:
        db.add_all([_item(value) for value in ("a", "b", "c")])
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        result = retriever.execute(
            _input(
                priority=["a", "b", "c"],
                revision={"revision_count": 1, "query_terms": ["source dispute"], "required_changes": ["check source"]},
                purpose="source_verification",
                n_results=2,
            )
        )

    assert result.query_text.endswith("source dispute")
    assert result.covered_knowledge_ids == ["a", "b"]
    assert result.missing_knowledge_ids == ["c"]
    assert "explicit_plan_exceeds_output_budget" in result.warnings


def test_v2_retrieval_excludes_missing_source_and_validates_collection_metadata(tmp_path: Path) -> None:
    sessions = _session()
    records = [_record("bad-source", 0, [1.0, 0.0, 0.0], source=False)]
    with sessions() as db:
        db.add(_item("bad-source"))
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        result = retriever.execute(_input(priority=["bad-source"]))
        assert result.chunks == []
        assert result.missing_knowledge_ids == ["bad-source"]
        assert "candidate_missing_source:bad-source::chunk::0" in result.warnings

        store, metadata = _manifest_store(tmp_path / "wrong", records)
        metadata["distance_metric"] = "l2"
        bad = V2CandidateRetriever(
            db=db,
            chroma_client=FakeClient(FakeCollection("knowledge_ai_app_dev_candidate_test", records, metadata)),
            embedding_provider=FakeProvider(),
            manifest_store=store,
        )
        with pytest.raises(V2RetrievalError, match="metadata mismatch"):
            bad.execute(_input(priority=["bad-source"]))


def test_v2_retrieval_ablation_modes_do_not_change_contract_shape(tmp_path: Path) -> None:
    sessions = _session()
    records = [_record("priority", 0, [1.0, 0.0, 0.0]), _record("semantic", 0, [0.9, 0.0, 0.0])]
    with sessions() as db:
        db.add_all([_item("priority"), _item("semantic")])
        db.commit()
        for mode in ("semantic-only", "explicit-only", "semantic+relation", "full"):
            retriever, _ = _retriever(tmp_path / mode, db, records, mode=mode)
            result = retriever.execute(_input(priority=["priority"]))
            assert result.task_id == "task-v2-1"
            assert len(result.chunks) <= 12
            assert result.model_dump()["contract_version"] == "agent-contract-v2"
