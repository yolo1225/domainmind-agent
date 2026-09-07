from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.contracts import RetrieveKnowledgeInput
from app.agents.retrieval_agent import KnowledgeRetrievalAgent
from app.models import Base, DiagnosticQuestion, KnowledgeItem, KnowledgeRelation
from app.rag.candidate_manifest import (
    DISTANCE_METRIC,
    MANIFEST_SCHEMA_VERSION,
    CandidateIndexManifest,
    CandidateManifestStore,
    compute_index_version,
)
from app.rag.retrieval import (
    CandidateRecord,
    CandidateRetriever,
    RetrievalError,
    _graded_quiz_question_scope,
    _record_capabilities,
)
from app.rag.database_manifest_store import DatabaseManifestStore
from app.agents.domain_evidence_policy import EvidenceCapability


def test_production_retrieval_reads_the_database_active_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runtime retrieval must use the same active-index pointer as readiness."""
    from app.agents import retrieval_agent

    captured: dict[str, Any] = {}

    class SpyRetriever:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(retrieval_agent, "CandidateRetriever", SpyRetriever)
    monkeypatch.setattr(retrieval_agent, "SessionLocal", lambda: object())
    monkeypatch.setattr(retrieval_agent, "VectorStore", lambda: SimpleNamespace(client=object()))
    monkeypatch.setattr(
        retrieval_agent,
        "settings",
        SimpleNamespace(
            openai_api_base="https://example.com/v1",
            openai_api_key="test-key",
            embedding_model="test-embedding",
            llm_timeout_seconds=15,
        ),
    )
    monkeypatch.setattr(
        retrieval_agent,
        "OpenAICompatibleEmbeddingProvider",
        lambda **_kwargs: object(),
    )

    KnowledgeRetrievalAgent.production()

    assert isinstance(captured["manifest_store"], DatabaseManifestStore)


def test_indexed_capabilities_override_domain_text_heuristics() -> None:
    record = CandidateRecord(
        chunk_id="maritime::chunk::0",
        document="操作步骤：执行命令并返回固定结果。",
        metadata={
            "knowledge_id": "maritime_rule",
            "evidence_capabilities": "concept",
        },
        embedding=None,
    )

    assert _record_capabilities(record, "maritime") == frozenset(
        {EvidenceCapability.CONCEPT}
    )


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
            "distances": [
                [
                    1 - sum(a * b for a, b in zip(query, record["embedding"], strict=True))
                    for record in ranked
                ]
            ],
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
            "heading_path": "[]",
            "embedding_model": "test-embedding",
            "embedding_dimensions": 3,
        },
    }


def _manifest_store(
    tmp_path: Path, records: list[dict[str, Any]]
) -> tuple[CandidateManifestStore, dict[str, Any]]:
    source_version = "sha256:" + "1" * 64
    metadata = {
        "domain_code": "ai_app_dev",
        "embedding_model": "test-embedding",
        "embedding_dimensions": 3,
        "distance_metric": DISTANCE_METRIC,
        "chunker_version": "candidate-heading-v3",
    }
    index_version = compute_index_version(
        domain_code="ai_app_dev",
        source_data_version=source_version,
        embedding_model="test-embedding",
        embedding_dimensions=3,
        distance_metric=DISTANCE_METRIC,
        chunker_version="candidate-heading-v3",
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
            chunker_version="candidate-heading-v3",
            index_version=index_version,
            source_data_version=source_version,
            last_successful_sync_at="2026-07-24T12:00:00+00:00",
            indexed_item_count=len({record["metadata"]["knowledge_id"] for record in records}),
            indexed_chunk_count=len(records),
        )
    )
    return store, metadata


def _input(
    *,
    priority=None,
    prerequisite=None,
    revision=None,
    purpose="remedial_explanation",
    n_results=8,
    resource_types=None,
    resource_knowledge_targets=None,
) -> RetrieveKnowledgeInput:
    requested_types = resource_types or ["lecture"]
    return RetrieveKnowledgeInput.model_validate(
        {
            "task_id": "task-v3-1",
            "context": {
                "task_id": "task-v3-1",
                "session_id": "session-v3-1",
                "trigger_type": "initial_generation",
                "execution_mode": "auto",
                "learner_id": "learner-v3",
                "profile_id": "profile-v3",
                "domain_code": "ai_app_dev",
                "resource_types": requested_types,
                "learning_goal": "Learn RAG retrieval",
                "resource_knowledge_targets": resource_knowledge_targets or {},
            },
            "profile": {
                "profile_id": "profile-v3",
                "profile_version": 1,
                "profile_type": "beginner",
                "ability_scores": {
                    "theory": 30,
                    "practice": 30,
                    "problem_solving": 30,
                    "knowledge_breadth": 30,
                    "learning_speed": 30,
                },
                "weak_knowledge": [
                    {
                        "knowledge_id": "weak-1",
                        "name": "Weak name",
                        "category": "Weak category",
                        "weakness_level": 4,
                        "mastery_type": "unmastered",
                        "reason": "diagnosis",
                    }
                ],
            },
            "retrieval_plan": {
                "strategy": "remedial",
                "target_difficulty": 2,
                "resource_types": requested_types,
                "priority_knowledge_ids": priority or [],
                "prerequisite_knowledge_ids": prerequisite or [],
                "query_terms": ["RAG", "retrieval"],
                "n_results": n_results,
            },
            "revision_plan": revision,
            "purpose": purpose,
        }
    )


def test_graded_quiz_scope_prefers_assigned_resource_targets() -> None:
    request = _input(
        priority=["embedding_basics", "related-topic"],
        resource_types=["lecture", "practice_guide", "graded_quiz"],
        resource_knowledge_targets={
            "lecture": ["embedding_basics", "related-topic"],
            "practice_guide": ["embedding_basics"],
            "graded_quiz": ["embedding_basics"],
        },
    )

    assert _graded_quiz_question_scope(
        request,
        ["embedding_basics", "related-topic"],
        ["embedding_basics", "related-topic"],
    ) == ["embedding_basics"]


def test_practice_retrieval_prefers_operational_chunk_for_same_knowledge(
    tmp_path: Path,
) -> None:
    sessions = _session()
    conceptual = _record("practice-target", 0, [1.0, 0.0, 0.0])
    operational = _record("practice-target", 1, [0.7, 0.0, 0.0])
    operational["document"] = "## 操作步骤\n1. 检查以下配置文件。"
    operational["metadata"]["heading_path"] = json.dumps(["操作步骤"], ensure_ascii=False)
    records = [conceptual, operational]
    with sessions() as db:
        db.add(_item("practice-target"))
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        result = retriever.execute(
            _input(
                priority=["practice-target"],
                n_results=1,
                resource_types=["lecture", "practice_guide"],
            )
        )

    assert result.chunks[0].chunk_id == "practice-target::chunk::1"
    assert not any("practice_operation_evidence_missing" in item for item in result.warnings)


def test_practice_retrieval_prefers_operation_heading_over_error_keyword_overlap(
    tmp_path: Path,
) -> None:
    sessions = _session()
    operation = _record("practice-target", 4, [0.7, 0.0, 0.0])
    operation["document"] = "1. 发起最小真实调用，并记录响应结构。"
    operation["metadata"]["heading_path"] = json.dumps(["操作步骤"], ensure_ascii=False)
    common_error = _record("practice-target", 6, [1.0, 0.0, 0.0])
    common_error["document"] = "常见错误包括：调用请求时记录完整隐私数据。"
    common_error["metadata"]["heading_path"] = json.dumps(["常见错误"], ensure_ascii=False)
    records = [operation, common_error]
    with sessions() as db:
        db.add(_item("practice-target"))
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        result = retriever.execute(
            _input(
                priority=["practice-target"],
                n_results=1,
                resource_types=["practice_guide"],
            )
        )

    assert result.chunks[0].chunk_id == "practice-target::chunk::4"


def test_practice_retrieval_keeps_late_operational_explicit_chunk(tmp_path: Path) -> None:
    sessions = _session()
    records = [
        _record("long-practice-target", index, [1.0 - index * 0.05, 0.0, 0.0]) for index in range(5)
    ]
    records[4]["document"] = "标题：调用输入 > 操作步骤\n\n" "1. 对照目标服务文档列出必需配置。"
    records[4]["metadata"]["heading_path"] = json.dumps(
        ["调用输入", "操作步骤"], ensure_ascii=False
    )
    with sessions() as db:
        db.add(_item("long-practice-target"))
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        result = retriever.execute(
            _input(
                priority=["long-practice-target"],
                n_results=1,
                resource_types=["practice_guide"],
            )
        )

    assert result.chunks[0].chunk_id == "long-practice-target::chunk::4"
    assert not any("practice_operation_evidence_missing" in item for item in result.warnings)


def test_practice_retrieval_keeps_operation_and_expected_result_for_same_target(
    tmp_path: Path,
) -> None:
    sessions = _session()
    concept = _record("practice-target", 0, [1.0, 0.0, 0.0])
    concept["document"] = "概念说明：向量嵌入用于表示文本语义。"
    operation = _record("practice-target", 1, [0.8, 0.0, 0.0])
    operation["document"] = "## 操作步骤\n1. 执行最小调用并记录响应。"
    expected = _record("practice-target", 2, [0.7, 0.0, 0.0])
    expected["document"] = "## 预期结果\n返回可用于后续检索的向量表示。"
    records = [concept, operation, expected]
    with sessions() as db:
        db.add(_item("practice-target"))
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        result = retriever.execute(
            _input(
                priority=["practice-target"],
                n_results=2,
                resource_types=["practice_guide"],
            )
        )

    assert [chunk.chunk_id for chunk in result.chunks] == [
        "practice-target::chunk::1",
        "practice-target::chunk::2",
    ]
    assert not any("practice_expected_result_evidence_missing" in item for item in result.warnings)


def test_practice_supplement_prefers_related_evidence_over_unrelated_labels(
    tmp_path: Path,
) -> None:
    sessions = _session()
    target = _record("target", 0, [1.0, 0.0, 0.0])
    related = _record("related-practice", 0, [0.6, 0.0, 0.0])
    related["document"] = "## 操作步骤\n1. 执行以下检查。"
    unrelated = _record("unrelated-practice", 0, [0.99, 0.0, 0.0])
    unrelated["document"] = (
        "## 操作步骤\n1. 执行以下命令。\n```bash\npython tool.py\n```\n"
        "预期结果：显示成功。\n失败时检查配置。"
    )
    records = [target, related, unrelated]
    with sessions() as db:
        target_item, related_item, unrelated_item = [
            _item(value)
            for value in ("target", "related-practice", "unrelated-practice")
        ]
        db.add_all([target_item, related_item, unrelated_item])
        db.flush()
        db.add(
            KnowledgeRelation(
                source_item_id=target_item.id,
                target_item_id=related_item.id,
                relation_type="related",
            )
        )
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        result = retriever.execute(
            _input(
                priority=["target"],
                n_results=2,
                resource_types=["practice_guide"],
            )
        )

    assert [chunk.knowledge_id for chunk in result.chunks] == [
        "target",
        "related-practice",
    ]


def _retriever(
    tmp_path: Path, db, records, *, mode="full", vector=None
) -> tuple[CandidateRetriever, FakeProvider]:
    store, metadata = _manifest_store(tmp_path, records)
    collection = FakeCollection("knowledge_ai_app_dev_candidate_test", records, metadata)
    provider = FakeProvider(vector)
    return CandidateRetriever(
        db=db,
        chroma_client=FakeClient(collection),
        embedding_provider=provider,
        manifest_store=store,
        mode=mode,
    ), provider


def test_v3_retrieval_combines_explicit_relation_and_semantic_with_real_cosine(
    tmp_path: Path,
) -> None:
    sessions = _session()
    records = [
        _record("priority", 0, [0.5, 0.5, 0.0]),
        _record("prerequisite", 0, [0.8, 0.2, 0.0]),
        _record("related", 0, [0.7, 0.0, 0.0]),
        _record("dependent", 0, [0.6, 0.0, 0.0]),
        _record("semantic", 0, [0.9, 0.0, 0.0]),
    ]
    with sessions() as db:
        priority, prerequisite, related, dependent, semantic = [
            _item(value)
            for value in ("priority", "prerequisite", "related", "dependent", "semantic")
        ]
        db.add_all([priority, prerequisite, related, dependent, semantic])
        db.flush()
        db.add_all(
            [
                KnowledgeRelation(
                    source_item_id=prerequisite.id,
                    target_item_id=priority.id,
                    relation_type="prerequisite",
                ),
                KnowledgeRelation(
                    source_item_id=priority.id,
                    target_item_id=dependent.id,
                    relation_type="prerequisite",
                ),
                KnowledgeRelation(
                    source_item_id=priority.id, target_item_id=related.id, relation_type="related"
                ),
            ]
        )
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


def test_v3_retrieval_keeps_revision_query_and_reports_explicit_budget(tmp_path: Path) -> None:
    sessions = _session()
    records = [_record(value, 0, [1.0, 0.0, 0.0]) for value in ("a", "b", "c")]
    with sessions() as db:
        db.add_all([_item(value) for value in ("a", "b", "c")])
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        result = retriever.execute(
            _input(
                priority=["a", "b", "c"],
                revision={
                    "revision_count": 1,
                    "query_terms": ["source dispute"],
                    "required_changes": ["check source"],
                },
                purpose="source_verification",
                n_results=2,
            )
        )

    assert result.query_text.endswith("source dispute")
    assert result.covered_knowledge_ids == ["a", "b"]
    assert result.missing_knowledge_ids == ["c"]
    assert "explicit_plan_exceeds_output_budget" in result.warnings


def test_related_question_under_minimum_density_stops_before_generation(tmp_path: Path) -> None:
    sessions = _session()
    target_ids = ["target-a", "target-b", "target-c"]
    primary_id = "question-primary"
    records = [
        _record("target-a", 0, [1.0, 0.0, 0.0]),
        _record("target-b", 0, [0.9, 0.1, 0.0]),
        _record("target-c", 0, [0.8, 0.2, 0.0]),
        _record(primary_id, 0, [0.2, 0.8, 0.0]),
        _record(primary_id, 1, [0.1, 0.9, 0.0]),
    ]
    exact_source_locator = f"{primary_id}::chunk::1"
    records[-1]["metadata"]["source_locator"] = exact_source_locator

    with sessions() as db:
        items = {public_id: _item(public_id) for public_id in [*target_ids, primary_id]}
        db.add_all(items.values())
        db.flush()
        db.add(
            DiagnosticQuestion(
                public_id="related-question",
                domain_code="ai_app_dev",
                knowledge_item_id=items[primary_id].id,
                related_knowledge_ids_json=["target-a"],
                question_type="single_choice",
                stem="哪一项描述正确？",
                options_json=["正确选项", "错误选项一", "错误选项二", "错误选项三"],
                answer_key_json={
                    "correct_option": 0,
                    "question_bank_uses": ["graded_quiz"],
                    "explanation": "解析来自题目主知识点的精确来源。",
                    "source_ref_ids": [exact_source_locator],
                    "quiz_level": "improvement",
                    "source_locators": {exact_source_locator: exact_source_locator},
                },
                difficulty=2,
                status="active",
            )
        )
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        with pytest.raises(ValueError, match="graded_quiz_question_bank_insufficient"):
            retriever.execute(
                _input(
                    priority=target_ids,
                    n_results=3,
                    resource_types=["graded_quiz"],
                )
            )


def test_lecture_only_retrieval_does_not_include_question_bank_sources(
    tmp_path: Path,
) -> None:
    sessions = _session()
    records = [
        _record("lecture-target", 0, [1.0, 0.0, 0.0]),
        _record("question-primary", 0, [0.2, 0.8, 0.0]),
    ]
    with sessions() as db:
        target = _item("lecture-target")
        primary = _item("question-primary")
        db.add_all([target, primary])
        db.flush()
        db.add(
            DiagnosticQuestion(
                public_id="lecture-unrelated-question",
                domain_code="ai_app_dev",
                knowledge_item_id=primary.id,
                related_knowledge_ids_json=["lecture-target"],
                question_type="single_choice",
                stem="不应进入讲义检索的题目",
                options_json=["A", "B", "C", "D"],
                answer_key_json={
                    "correct_option": 0,
                    "question_bank_uses": ["graded_quiz"],
                    "explanation": "可信解析。",
                    "source_ref_ids": ["question-primary::chunk::0"],
                    "quiz_level": "foundation",
                    "source_locators": {
                        "question-primary::chunk::0": "question-primary::chunk::0"
                    },
                },
                difficulty=1,
                status="active",
            )
        )
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        result = retriever.execute(
            _input(priority=["lecture-target"], n_results=1, resource_types=["lecture"])
        )

    assert result.reference_questions == []
    assert [chunk.knowledge_id for chunk in result.chunks] == ["lecture-target"]


def test_two_questions_on_same_primary_knowledge_are_density_insufficient(
    tmp_path: Path,
) -> None:
    sessions = _session()
    records = [
        _record("target", 0, [1.0, 0.0, 0.0]),
        _record("shared-primary", 0, [0.3, 0.7, 0.0]),
        _record("shared-primary", 1, [0.2, 0.8, 0.0]),
    ]
    for record in records:
        record["metadata"]["source_locator"] = record["id"]
    with sessions() as db:
        target = _item("target")
        primary = _item("shared-primary")
        db.add_all([target, primary])
        db.flush()
        for index in range(2):
            db.add(
                DiagnosticQuestion(
                    public_id=f"shared-primary-question-{index}",
                    domain_code="ai_app_dev",
                    knowledge_item_id=primary.id,
                    related_knowledge_ids_json=["target"],
                    question_type="single_choice",
                    stem=f"共享主知识点题目 {index}",
                    options_json=["A", "B", "C", "D"],
                    answer_key_json={
                        "correct_option": 0,
                        "question_bank_uses": ["graded_quiz"],
                        "explanation": "可信解析。",
                        "source_ref_ids": [f"shared-primary::chunk::{index}"],
                        "quiz_level": "improvement",
                        "source_locators": {
                            f"shared-primary::chunk::{index}": f"shared-primary::chunk::{index}"
                        },
                    },
                    difficulty=2,
                    status="active",
                )
            )
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        with pytest.raises(ValueError, match="graded_quiz_question_bank_insufficient"):
            retriever.execute(
                _input(priority=["target"], n_results=1, resource_types=["graded_quiz"])
            )


def test_quiz_source_supplements_expand_within_v9_chunk_budget(tmp_path: Path) -> None:
    sessions = _session()
    target_ids = ["target-a", "target-b", "target-c"]
    related_primary_ids = ["related-primary-a", "related-primary-b", "related-primary-c"]
    semantic_ids = [f"semantic-{index}" for index in range(9)]
    all_ids = [*target_ids, *related_primary_ids, *semantic_ids]
    records = [
        *[
            _record(public_id, 0, [1.0 - index * 0.01, 0.0, 0.0])
            for index, public_id in enumerate(target_ids)
        ],
        *[
            _record(public_id, 0, [0.8 - index * 0.01, 0.0, 0.0])
            for index, public_id in enumerate(semantic_ids)
        ],
        *[
            _record(public_id, 0, [0.2 - index * 0.01, 0.0, 0.0])
            for index, public_id in enumerate(related_primary_ids)
        ],
    ]
    for record in records:
        record["metadata"]["source_locator"] = record["id"]

    question_specs = [
        ("question-foundation-a", "target-a", [], "foundation"),
        ("question-foundation-b", "target-b", [], "foundation"),
        ("question-improvement-a", "related-primary-a", ["target-a"], "improvement"),
        ("question-improvement-b", "related-primary-b", ["target-b"], "improvement"),
        ("question-challenge-a", "related-primary-c", ["target-c"], "challenge"),
        ("question-challenge-b", "target-c", [], "challenge"),
    ]
    with sessions() as db:
        items = {public_id: _item(public_id) for public_id in all_ids}
        db.add_all(items.values())
        db.flush()
        for question_id, primary_id, related_ids, quiz_level in question_specs:
            db.add(
                DiagnosticQuestion(
                    public_id=question_id,
                    domain_code="ai_app_dev",
                    knowledge_item_id=items[primary_id].id,
                    related_knowledge_ids_json=related_ids,
                    question_type="single_choice",
                    stem=f"{question_id} 的正确答案是什么？",
                    options_json=["A", "B", "C", "D"],
                    answer_key_json={
                        "correct_option": 0,
                        "question_bank_uses": ["graded_quiz"],
                        "explanation": "可信解析。",
                        "source_ref_ids": [f"{primary_id}::chunk::0"],
                        "quiz_level": quiz_level,
                        "source_locators": {
                            f"{primary_id}::chunk::0": f"{primary_id}::chunk::0"
                        },
                    },
                    difficulty=2,
                    status="active",
                )
            )
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        result = retriever.execute(
            _input(
                priority=target_ids,
                n_results=12,
                resource_types=["lecture", "practice_guide", "graded_quiz"],
            )
        )

    assert len(result.reference_questions) == 5
    assert len(result.chunks) == 12
    chunk_knowledge_ids = {chunk.knowledge_id for chunk in result.chunks}
    assert all(
        {question.knowledge_id, *question.related_knowledge_ids} & chunk_knowledge_ids
        for question in result.reference_questions
    )
    assert set(target_ids) <= chunk_knowledge_ids


def test_six_knowledge_unit_and_six_external_quiz_sources_fit_chunk_budget(
    tmp_path: Path,
) -> None:
    sessions = _session()
    target_ids = [f"target-{index}" for index in range(6)]
    question_primary_ids = [f"question-primary-{index}" for index in range(6)]
    filler_ids = [f"semantic-filler-{index}" for index in range(6)]
    records = [
        *[
            _record(public_id, 0, [1.0 - index * 0.01, 0.0, 0.0])
            for index, public_id in enumerate(target_ids)
        ],
        *[
            _record(public_id, 0, [0.8 - index * 0.01, 0.0, 0.0])
            for index, public_id in enumerate(filler_ids)
        ],
        *[
            _record(public_id, 0, [0.2 - index * 0.01, 0.0, 0.0])
            for index, public_id in enumerate(question_primary_ids)
        ],
    ]
    for record in records:
        record["metadata"]["source_locator"] = record["id"]

    quiz_levels = ["foundation", "foundation", "improvement", "improvement", "challenge", "challenge"]
    all_ids = [*target_ids, *question_primary_ids, *filler_ids]
    with sessions() as db:
        items = {public_id: _item(public_id) for public_id in all_ids}
        db.add_all(items.values())
        db.flush()
        for index, (primary_id, quiz_level) in enumerate(
            zip(question_primary_ids, quiz_levels, strict=True)
        ):
            db.add(
                DiagnosticQuestion(
                    public_id=f"six-point-question-{index}",
                    domain_code="ai_app_dev",
                    knowledge_item_id=items[primary_id].id,
                    related_knowledge_ids_json=[target_ids[index]],
                    question_type="single_choice",
                    stem=f"第 {index + 1} 道可信题目的正确答案是什么？",
                    options_json=["A", "B", "C", "D"],
                    answer_key_json={
                        "correct_option": 0,
                        "question_bank_uses": ["graded_quiz"],
                        "explanation": "可信解析。",
                        "source_ref_ids": [f"{primary_id}::chunk::0"],
                        "quiz_level": quiz_level,
                        "source_locators": {
                            f"{primary_id}::chunk::0": f"{primary_id}::chunk::0"
                        },
                    },
                    difficulty=2,
                    status="active",
                )
            )
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        result = retriever.execute(
            _input(
                priority=target_ids,
                n_results=12,
                resource_types=["lecture", "practice_guide", "graded_quiz"],
            )
        )

    chunk_knowledge_ids = {chunk.knowledge_id for chunk in result.chunks}
    assert len(result.chunks) == 12
    assert len(result.reference_questions) == 6
    assert set(target_ids) <= chunk_knowledge_ids
    assert all(
        {question.knowledge_id, *question.related_knowledge_ids} & chunk_knowledge_ids
        for question in result.reference_questions
    )


def test_v3_retrieval_excludes_missing_source_and_validates_collection_metadata(
    tmp_path: Path,
) -> None:
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
        bad = CandidateRetriever(
            db=db,
            chroma_client=FakeClient(
                FakeCollection("knowledge_ai_app_dev_candidate_test", records, metadata)
            ),
            embedding_provider=FakeProvider(),
            manifest_store=store,
        )
        with pytest.raises(RetrievalError, match="metadata mismatch"):
            bad.execute(_input(priority=["bad-source"]))


def test_v3_retrieval_ablation_modes_do_not_change_contract_shape(tmp_path: Path) -> None:
    sessions = _session()
    records = [_record("priority", 0, [1.0, 0.0, 0.0]), _record("semantic", 0, [0.9, 0.0, 0.0])]
    with sessions() as db:
        db.add_all([_item("priority"), _item("semantic")])
        db.commit()
        for mode in ("semantic-only", "explicit-only", "semantic+relation", "full"):
            retriever, _ = _retriever(tmp_path / mode, db, records, mode=mode)
            result = retriever.execute(_input(priority=["priority"]))
            assert result.task_id == "task-v3-1"
            assert len(result.chunks) <= 18
    assert result.model_dump()["contract_version"] == "agent-contract-v10"


def test_v3_retrieval_rejects_cross_domain_chunk(tmp_path: Path) -> None:
    sessions = _session()
    records = [_record("priority", 0, [1.0, 0.0, 0.0])]
    records[0]["metadata"]["domain_code"] = "other_domain"
    with sessions() as db:
        db.add(_item("priority"))
        db.commit()
        retriever, _ = _retriever(tmp_path, db, records)
        with pytest.raises(RetrievalError, match="cross-domain chunk rejected"):
            retriever.execute(_input(priority=["priority"]))
