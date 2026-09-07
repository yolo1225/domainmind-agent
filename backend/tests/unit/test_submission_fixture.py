from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    Domain,
    KnowledgeDocument,
    KnowledgeItem,
    KnowledgeRelation,
    Learner,
    LearnerProfile,
    LearningPath,
)
from app.models.base import Base
from app.scripts import submission_fixture
from app.scripts.submission_fixture import validate_submission_fixture
from app.services.domain_runtime_service import load_domain_runtime
from app.services.knowledge_document_service import serialize_document
from app.services.profile_service import is_initial_profile_ready


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = PROJECT_ROOT / "data" / "submission_fixtures" / "ai_app_dev_v1"
SMART_FIXTURE_DIR = PROJECT_ROOT / "data" / "submission_fixtures" / "smart_manufacturing_v1"


def test_submission_fixture_is_complete_and_hash_locked() -> None:
    result = validate_submission_fixture(FIXTURE_DIR)

    assert result["fixture_version"] == "ai_app_dev_submission_fixture_v1"
    assert result["counts"] == {
        "knowledge_items": 75,
        "knowledge_relations": 106,
        "prerequisite_relations": 92,
        "related_relations": 14,
        "active_questions": 465,
        "question_purposes": {
            "diagnosis": 90,
            "graded_quiz": 225,
            "mastery_validation": 150,
        },
        "template_compatible_questions": 450,
        "supplemental_diagnosis_questions": 15,
        "evaluation_cases": 50,
        "manual_demo_cases": 3,
    }


def test_submission_fixture_loads_once_and_is_idempotent(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(submission_fixture, "SessionLocal", factory)

    loaded = submission_fixture.load_submission_fixture(FIXTURE_DIR)
    repeated = submission_fixture.load_submission_fixture(FIXTURE_DIR)

    assert loaded["database"]["status"] == "loaded"
    assert repeated["database"]["status"] == "already_loaded"
    assert loaded["database"]["knowledge_items"] == 75
    assert loaded["database"]["knowledge_relations"] == 106
    assert loaded["database"]["active_questions"] == 465
    with factory() as db:
        document = db.scalar(select(KnowledgeDocument))
        items = list(db.scalars(select(KnowledgeItem)))
        relations = list(db.scalars(select(KnowledgeRelation)))

    assert document is not None
    assert serialize_document(document)["is_system"] is True
    connected_item_ids = {
        item_id
        for relation in relations
        for item_id in (relation.source_item_id, relation.target_item_id)
    }
    assert {item.id for item in items}.issubset(connected_item_ids)


def test_submission_fixture_rejects_foreign_domain(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(submission_fixture, "SessionLocal", factory)
    with factory() as db:
        db.add(
            Domain(
                domain_code="foreign_domain",
                name="Foreign domain",
                status="ready",
                schema_version="1.0",
                config_json={},
            )
        )
        db.commit()

    with pytest.raises(
        submission_fixture.SubmissionFixtureError,
        match="fixture_requires_empty_database_or_same_fixture",
    ):
        submission_fixture.load_submission_fixture(FIXTURE_DIR)


def test_smart_manufacturing_fixture_is_hash_locked_without_evaluation_cases() -> None:
    result = validate_submission_fixture(SMART_FIXTURE_DIR)

    assert result["fixture_version"] == "smart_manufacturing_submission_fixture_v1"
    assert result["domain_code"] == "smart_manufacturing"
    assert result["counts"] == {
        "knowledge_items": 67,
        "knowledge_relations": 49,
        "active_questions": 402,
        "question_purposes": {
            "diagnosis": 67,
            "graded_quiz": 201,
            "mastery_validation": 134,
        },
        "template_compatible_questions": 402,
        "supplemental_diagnosis_questions": 0,
        "evaluation_cases": 0,
        "manual_demo_cases": 3,
        "learner_profiles": 3,
    }
    assert not (SMART_FIXTURE_DIR / "evaluation_cases_v4.json").exists()


def test_smart_manufacturing_fixture_loads_profiles_idempotently_and_is_runtime_ready(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(submission_fixture, "SessionLocal", factory)
    monkeypatch.setattr(
        "app.services.domain_runtime_service.candidate_rag_status",
        lambda domain_code: {
            "ready": True,
            "domain_code": domain_code,
            "active_collection": f"knowledge_{domain_code}_candidate_test",
            "indexed_chunk_count": 67,
            "index_version": "test-v1",
        },
    )

    loaded = submission_fixture.load_submission_fixture(SMART_FIXTURE_DIR)
    repeated = submission_fixture.load_submission_fixture(SMART_FIXTURE_DIR)

    assert loaded["database"]["status"] == "loaded"
    assert repeated["database"]["status"] == "already_loaded"
    assert loaded["database"]["learners"] == 3
    assert loaded["database"]["learner_profiles"] == 3
    assert loaded["database"]["learning_paths"] == 3
    with factory() as db:
        profiles = list(db.scalars(select(LearnerProfile).order_by(LearnerProfile.public_id)))
        learners = list(db.scalars(select(Learner).order_by(Learner.public_id)))
        paths = list(db.scalars(select(LearningPath).order_by(LearningPath.public_id)))
        runtime = load_domain_runtime(db, "smart_manufacturing")

    assert len(learners) == len(profiles) == len(paths) == 3
    assert all(learner.is_evaluation for learner in learners)
    assert all(is_initial_profile_ready(profile) for profile in profiles)
    assert {profile.ability_profile_json["profile_type"] for profile in profiles} == {
        "beginner",
        "intermediate",
        "advanced",
    }
    assert runtime.profile_ready is True
    assert runtime.diagnostic_ready is True
    assert runtime.question_bank_ready is True
    assert runtime.generation_ready is True
