from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.knowledge import get_vector_store
from app.core.db import get_db
from app.main import app
from app.models import Base, KnowledgeItem, Learner, LearnerProfile, LearningPath


def build_test_session() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def test_list_knowledge_items_reads_database() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        db.add(
            KnowledgeItem(
                public_id="rag_chunking",
                domain_code="ai_app_dev",
                name="RAG 文档切片策略",
                category="RAG",
                difficulty=3,
                tags_json=["rag", "retrieval"],
                content_md="切片需要平衡语义完整性、召回粒度和上下文窗口占用。",
                source_title="自建 AI 应用开发实训知识库",
                license_note="team-authored",
                needs_reembedding=False,
            )
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/v1/knowledge/items?domain_code=ai_app_dev")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["knowledge_id"] == "rag_chunking"
    assert body["data"]["items"][0]["tags"] == ["rag", "retrieval"]


def test_create_knowledge_item_marks_index_and_learning_paths() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner = Learner(public_id="learner_001", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_001",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            ability_profile_json={},
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
        db.add(
            LearningPath(
                public_id="path_001",
                learner_id=learner.id,
                profile_id=profile.id,
                domain_code="ai_app_dev",
                path_json={},
                needs_refresh=False,
            )
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/knowledge/items",
            json={
                "domain_code": "ai_app_dev",
                "name": "提示词变量控制",
                "category": "Prompt Engineering",
                "difficulty": 2,
                "tags": ["prompt", "variable"],
                "content": "提示词变量控制需要明确输入变量、约束条件、输出格式和失败处理策略。",
                "source_title": "教师手动导入",
                "license_note": "manual-import",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["item"]["name"] == "提示词变量控制"
    assert body["item"]["needs_reembedding"] is True
    assert body["index_status"] == "needs_rebuild"
    assert body["affected_learning_paths"] == 1

    with testing_session() as db:
        path = db.scalar(select(LearningPath).where(LearningPath.public_id == "path_001"))
        assert path is not None
        assert path.needs_refresh is True
        assert path.path_json["knowledge_update_reason"] == "manual_import"


def test_search_knowledge_returns_vector_matches() -> None:
    class FakeVectorStore:
        def query(self, **kwargs):
            assert kwargs["domain_code"] == "ai_app_dev"
            assert kwargs["n_results"] == 1
            return {
                "ids": [["rag_chunking::chunk::0"]],
                "documents": [["知识点：RAG 文档切片策略\n\n切片需要平衡语义完整性。"]],
                "metadatas": [
                    [
                        {
                            "knowledge_id": "rag_chunking",
                            "name": "RAG 文档切片策略",
                            "category": "RAG",
                            "difficulty": 3,
                            "source_title": "自建 AI 应用开发实训知识库",
                        }
                    ]
                ],
                "distances": [[0.12]],
            }

    app.dependency_overrides[get_vector_store] = lambda: FakeVectorStore()
    try:
        client = TestClient(app)
        response = client.get("/api/v1/knowledge/search?query=RAG切片&n_results=1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["matches"][0]["knowledge_id"] == "rag_chunking"
    assert body["data"]["matches"][0]["distance"] == 0.12
