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


def test_create_knowledge_item_marks_index_without_refreshing_unrelated_paths() -> None:
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
    assert body["affected_learning_paths"] == 0

    with testing_session() as db:
        path = db.scalar(select(LearningPath).where(LearningPath.public_id == "path_001"))
        assert path is not None
        assert path.needs_refresh is False


def test_update_knowledge_item_marks_pending_index() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        db.add(
            KnowledgeItem(
                public_id="knowledge_update_target",
                domain_code="ai_app_dev",
                name="旧名称",
                category="RAG",
                difficulty=2,
                tags_json=[],
                content_md="这是修改之前的知识点内容。",
                source_title="测试来源",
                license_note="test",
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
        response = TestClient(app).patch(
            "/api/v1/knowledge/items/knowledge_update_target",
            json={"name": "新名称", "content": "这是修改之后的知识点内容，必须重新生成向量。"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["item"]["name"] == "新名称"
    assert data["item"]["needs_reembedding"] is True
    assert data["affected_knowledge_ids"] == ["knowledge_update_target"]


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


def test_rebuild_index_executes_pending_item_synchronously(monkeypatch) -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        db.add(
            KnowledgeItem(
                public_id="pending_index_item",
                domain_code="ai_app_dev",
                name="待同步知识",
                category="RAG",
                difficulty=2,
                tags_json=["rag"],
                content_md="这是需要同步到向量数据库的完整知识内容。",
                source_title="测试来源",
                license_note="test",
                needs_reembedding=True,
            )
        )
        db.commit()

    class FakeCollection:
        def count(self):
            return 1

    class FakeVectorStore:
        def __init__(self):
            self.upserted = []

        def delete_knowledge_chunks(self, **kwargs):
            return 2

        def upsert_chunks(self, **kwargs):
            self.upserted.extend(kwargs["ids"])

        def get_collection(self, domain_code):
            return FakeCollection()

        def collection_name(self, domain_code):
            return f"knowledge_{domain_code}"

        def connection_info(self):
            return {"mode": "test"}

    fake_store = FakeVectorStore()

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_vector_store] = lambda: fake_store
    monkeypatch.setattr(
        "app.scripts.build_chroma_index.embed_texts",
        lambda documents: [[0.1, 0.2] for _ in documents],
    )
    try:
        response = TestClient(app).post("/api/v1/knowledge/rebuild-index")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "completed"
    assert data["indexed_items"] == 1
    assert data["deleted_chunks"] == 2
    assert fake_store.upserted == ["pending_index_item::chunk::0"]
    with testing_session() as db:
        item = db.scalar(select(KnowledgeItem))
        assert item is not None
        assert item.needs_reembedding is False
