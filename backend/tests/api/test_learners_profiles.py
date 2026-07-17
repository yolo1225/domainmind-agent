from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.main import app
from app.models import Base, Learner, LearnerProfile, LearningPath


def build_test_session() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def make_override(testing_session: sessionmaker[Session]):
    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    return override_get_db


def test_list_learners_returns_not_started_without_profile() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        db.add(
            Learner(
                public_id="learner_no_profile",
                background="零基础学习者",
                target_domain="ai_app_dev",
                experience_years=0,
                learning_style="mixed",
            )
        )
        db.commit()

    app.dependency_overrides[get_db] = make_override(testing_session)
    try:
        response = TestClient(app).get("/api/v1/learners")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"][0]
    assert data["learner_id"] == "learner_no_profile"
    assert data["profile_status"] == "not_started"
    assert data["ability_level"] == 0


def test_create_learner_returns_not_started_summary_and_is_listed() -> None:
    testing_session = build_test_session()
    app.dependency_overrides[get_db] = make_override(testing_session)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/learners",
            json={
                "learner_id": "learner_new",
                "background": "有一点 Python 基础，准备学习 RAG 应用开发",
                "target_domain": "ai_app_dev",
                "experience_years": 1,
                "learning_style": "practice",
            },
        )
        list_response = client.get("/api/v1/learners")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["learner_id"] == "learner_new"
    assert data["target_domain"] == "ai_app_dev"
    assert data["profile_status"] == "not_started"
    assert data["ability_level"] == 0
    assert any(item["learner_id"] == "learner_new" for item in list_response.json()["data"])


def test_create_learner_rejects_duplicate_public_id() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        db.add(Learner(public_id="learner_exists", target_domain="ai_app_dev"))
        db.commit()

    app.dependency_overrides[get_db] = make_override(testing_session)
    try:
        response = TestClient(app).post(
            "/api/v1/learners",
            json={
                "learner_id": "learner_exists",
                "background": "重复学习者",
                "target_domain": "ai_app_dev",
                "experience_years": 0,
                "learning_style": "mixed",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409


def test_get_profile_and_report_share_radar_values() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner = Learner(
            public_id="learner_ready",
            background="有 Python 基础",
            target_domain="ai_app_dev",
            experience_years=1,
            learning_style="practice",
        )
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_ready",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            ability_profile_json={
                "profile_type": "intermediate",
                "theory": 70,
                "practice": 75,
                "problem_solving": 68,
                "breadth": 60,
                "learning_speed": 72,
                "category_mastery": {"RAG 实操": 75},
            },
            weak_knowledge_json=[
                {
                    "knowledge_id": "rag_chunking",
                    "name": "RAG 切片策略",
                    "category": "RAG 实操",
                    "weakness_level": 3,
                }
            ],
        )
        db.add(profile)
        db.flush()
        db.add(
            LearningPath(
                public_id="path_ready",
                learner_id=learner.id,
                profile_id=profile.id,
                domain_code="ai_app_dev",
                path_json={
                    "stages": [
                        {"name": "攻克薄弱知识点", "description": "集中练习 RAG 切片。"}
                    ]
                },
                needs_refresh=False,
            )
        )
        db.commit()

    app.dependency_overrides[get_db] = make_override(testing_session)
    try:
        client = TestClient(app)
        profile_response = client.get("/api/v1/learners/learner_ready/profile")
        report_response = client.get("/api/v1/reports/learners/learner_ready")
    finally:
        app.dependency_overrides.clear()

    assert profile_response.status_code == 200
    assert report_response.status_code == 200
    profile_data = profile_response.json()["data"]
    report_data = report_response.json()["data"]
    assert profile_data["profile_status"] == "ready"
    assert profile_data["radar"] == [70, 75, 68, 60, 72]
    assert report_data["radar"] == profile_data["radar"]
    assert report_data["path"] == ["攻克薄弱知识点"]
