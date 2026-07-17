from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.main import app
from app.models import (
    Base,
    GenerationTask,
    GraphCheckpoint,
    Learner,
    LearnerProfile,
    LearningResource,
    ManualReviewTask,
)


def build_test_session() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def override(testing_session: sessionmaker[Session]):
    def get_test_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    return get_test_db


def seed_resource(db: Session):
    learner = Learner(
        public_id="learner_001",
        background="test",
        target_domain="ai_app_dev",
        learning_style="mixed",
    )
    db.add(learner)
    db.flush()
    profile = LearnerProfile(
        public_id="profile_001",
        learner_id=learner.id,
        ability_profile_json={"profile_type": "beginner"},
        weak_knowledge_json=[],
    )
    db.add(profile)
    db.flush()
    task = GenerationTask(
        public_id="task_visible",
        learner_id=learner.id,
        profile_id=profile.id,
        status="completed",
        decision="completed",
        resource_types_json=["lecture"],
    )
    db.add(task)
    db.flush()
    visible = LearningResource(
        public_id="resource_visible",
        generation_task_id=task.id,
        resource_type="lecture",
        title="通过资源",
        content_md="正文",
        difficulty=2,
        sources_json=[{"knowledge_id": "AIAPP-K029"}],
        review_status="passed",
        series_id="resource_visible",
        is_current=True,
    )
    hidden = LearningResource(
        public_id="resource_hidden",
        generation_task_id=task.id,
        resource_type="lecture",
        title="未发布草稿",
        content_md="草稿",
        difficulty=2,
        sources_json=[],
        review_status="revision_required",
        series_id="resource_hidden",
        is_current=True,
    )
    db.add_all([visible, hidden])
    db.commit()
    return learner, profile, task, visible


def test_resource_visibility_tutoring_and_feedback_contract(monkeypatch) -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        seed_resource(db)
    monkeypatch.setattr("app.api.v1.resources.run_generation_task", lambda task_id: None)
    monkeypatch.setattr("app.api.v1.tutoring.run_generation_task", lambda task_id: None)
    app.dependency_overrides[get_db] = override(testing_session)
    client = TestClient(app)
    try:
        resources = client.get("/api/v1/resources").json()["data"]
        assert [item["resource_id"] for item in resources] == ["resource_visible"]
        admin_resources = client.get(
            "/api/v1/resources?include_unpublished=true"
        ).json()["data"]
        assert {item["resource_id"] for item in admin_resources} == {
            "resource_visible",
            "resource_hidden",
        }

        session_response = client.post(
            "/api/v1/tutoring/sessions", json={"resource_id": "resource_visible"}
        )
        session_id = session_response.json()["data"]["session_id"]
        message = client.post(
            f"/api/v1/tutoring/sessions/{session_id}/messages",
            json={"content": "这部分太难，我看不懂"},
        ).json()["data"]
        assert message["profile_update_required"] is False
        assert message["task_id"] is None

        feedback = client.post(
            "/api/v1/resources/resource_visible/feedback",
            json={"feedback_type": "too_hard", "rating": 2},
        ).json()["data"]
        assert feedback["profile_update_required"] is False
        assert feedback["task_id"] is None
    finally:
        app.dependency_overrides.clear()


def test_manual_review_resumes_same_thread(monkeypatch) -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        _, _, task, _ = seed_resource(db)
        task.status = "waiting_human"
        task.decision = "manual_review_required"
        review = ManualReviewTask(
            public_id="mr_task_visible",
            task_id=task.id,
            trigger_reason="model_disagreement",
            status="pending",
        )
        checkpoint = GraphCheckpoint(
            task_id=task.public_id,
            checkpoint_id="cp_1",
            state_json={"native_checkpoint": True},
            next_node="human_review",
            status="waiting_human",
        )
        db.add_all([review, checkpoint])
        db.commit()
    monkeypatch.setattr("app.api.v1.manual_reviews.run_generation_task", lambda task_id: None)
    app.dependency_overrides[get_db] = override(testing_session)
    try:
        response = TestClient(app).post(
            "/api/v1/manual-reviews/mr_task_visible/decision",
            json={"decision": "approve", "comment": "证据已核验"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["task_id"] == "task_visible"
        assert data["resume_thread_id"] == "task_visible"
        with testing_session() as db:
            review = db.scalar(
                select(ManualReviewTask).where(
                    ManualReviewTask.public_id == "mr_task_visible"
                )
            )
            assert review.decision == "approve"
            assert review.status == "resolved"
    finally:
        app.dependency_overrides.clear()
