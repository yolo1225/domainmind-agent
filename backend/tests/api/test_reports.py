from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.main import app
from app.models import (
    Base,
    Feedback,
    GenerationTask,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
    ReviewReport,
)


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


def test_report_returns_empty_loop_summary_for_new_learner() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        db.add(
            Learner(
                public_id="learner_report_empty",
                background="new learner",
                target_domain="ai_app_dev",
                experience_years=0,
                learning_style="mixed",
            )
        )
        db.commit()

    app.dependency_overrides[get_db] = make_override(testing_session)
    try:
        response = TestClient(app).get("/api/v1/reports/learners/learner_report_empty")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["loop_status"]["profile"] == "pending"
    assert data["loop_status"]["generation"] == "pending"
    assert data["resource_summary"]["total"] == 0
    assert data["review_summary"]["total_reports"] == 0
    assert data["feedback_summary"]["total"] == 0
    assert data["next_actions"][0]["type"] == "diagnosis"


def test_report_summarizes_resources_reviews_feedback_and_path_refresh() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner = Learner(
            public_id="learner_report_ready",
            background="ready learner",
            target_domain="ai_app_dev",
            experience_years=1,
            learning_style="practice",
        )
        db.add(learner)
        db.flush()

        profile = LearnerProfile(
            public_id="profile_report_ready",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            ability_profile_json={
                "profile_type": "intermediate",
                "theory": 70,
                "practice": 75,
                "problem_solving": 68,
                "breadth": 60,
                "learning_speed": 72,
            },
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()

        task = GenerationTask(
            public_id="task_report_ready",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="completed",
            resource_types_json=["lecture", "practice_guide", "graded_quiz"],
            decision="passed",
        )
        db.add(task)
        db.flush()

        resources = [
            LearningResource(
                public_id="res_report_lecture",
                generation_task_id=task.id,
                resource_type="lecture",
                title="Lecture",
                content_md="content",
                difficulty=3,
                learner_profile_type="intermediate",
                sources_json=[{"knowledge_id": "ki_1"}, {"knowledge_id": "ki_2"}],
                review_status="passed",
            ),
            LearningResource(
                public_id="res_report_practice",
                generation_task_id=task.id,
                resource_type="practice_guide",
                title="Practice",
                content_md="content",
                difficulty=3,
                learner_profile_type="intermediate",
                sources_json=[{"knowledge_id": "ki_2"}],
                review_status="passed",
            ),
        ]
        db.add_all(resources)
        db.flush()

        db.add_all(
            [
                ReviewReport(resource_id=resources[0].id, passed=True),
                ReviewReport(resource_id=resources[1].id, passed=True),
                Feedback(
                    resource_id=resources[0].id,
                    learner_id=learner.id,
                    rating=3,
                    feedback_type="confusing",
                    feedback_summary_json={},
                    triggered_action="remedial_explanation",
                ),
                LearningPath(
                    public_id="path_report_ready",
                    learner_id=learner.id,
                    profile_id=profile.id,
                    domain_code="ai_app_dev",
                    path_json={"stages": [{"name": "Stage 1"}]},
                    needs_refresh=True,
                ),
            ]
        )
        db.commit()

    app.dependency_overrides[get_db] = make_override(testing_session)
    try:
        response = TestClient(app).get("/api/v1/reports/learners/learner_report_ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["loop_status"]["profile"] == "completed"
    assert data["loop_status"]["generation"] == "completed"
    assert data["loop_status"]["review"] == "completed"
    assert data["loop_status"]["feedback"] == "completed"
    assert data["loop_status"]["path_update"] == "refreshed"
    assert data["resource_summary"]["total"] == 2
    assert data["resource_summary"]["by_type"]["lecture"] == 1
    assert data["review_summary"]["passed"] == 2
    assert data["review_summary"]["source_coverage"] == 2
    assert data["feedback_summary"]["total"] == 1
    assert data["feedback_summary"]["latest_action"] == "remedial_explanation"
    assert data["feedback_summary"]["learning_path_needs_refresh"] is False
    assert data["feedback_summary"]["path_refresh_performed"] is True
    with testing_session() as db:
        path = db.scalar(select(LearningPath).where(LearningPath.public_id == "path_report_ready"))
        assert path is not None
        assert path.needs_refresh is False
        assert path.path_json["refreshed_at"]
