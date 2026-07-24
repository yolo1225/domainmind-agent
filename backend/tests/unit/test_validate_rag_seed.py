from copy import deepcopy

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, DiagnosticQuestion, KnowledgeItem, KnowledgeRelation
from app.scripts.seed_data import seed_diagnostic_questions, seed_knowledge_items
from app.scripts.validate_rag_seed import (
    RETIRED_KNOWLEDGE_IDS,
    SeedValidationError,
    load_diagnostic_questions,
    load_knowledge_items,
    source_data_version,
    validate_diagnostic_questions,
    validate_knowledge_items,
    validate_seed,
)


def test_repository_rag_seed_meets_frozen_baseline() -> None:
    items = load_knowledge_items()

    result = validate_seed()

    assert result["status"] == "passed"
    assert result["counts"] == {
        "knowledge_items": 50,
        "unique_knowledge_ids": 50,
        "prerequisite_relations": 67,
        "related_relations": 14,
        "invalid_relations": 0,
        "self_relations": 0,
    }
    assert result["sources"]["complete_required_fields"] == 50
    assert result["sources"]["with_source_url"] == 50
    assert result["sources"]["required_field_completeness"] == 1.0
    assert result["content"]["over_800_characters"] >= 3
    assert result["diagnostic_questions"] == {
        "total": 60,
        "unique_question_ids": 60,
        "single_choice": 50,
        "short_answer": 10,
        "invalid_knowledge_references": 0,
    }
    assert RETIRED_KNOWLEDGE_IDS.isdisjoint(item["knowledge_id"] for item in items)


def test_source_data_version_is_order_independent_and_content_sensitive() -> None:
    items = load_knowledge_items()
    original = source_data_version(items)

    assert source_data_version(list(reversed(items))) == original

    changed = deepcopy(items)
    changed[0]["content"] += "变更"
    assert source_data_version(changed) != original


def test_validated_seed_loads_through_existing_database_seed_path() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as db:
        seeded = seed_knowledge_items(db)
        questions = seed_diagnostic_questions(db, seeded)
        db.flush()

        assert len(seeded) == 50
        assert len(questions) == 60
        assert db.scalar(select(func.count()).select_from(KnowledgeItem)) == 50
        assert db.scalar(select(func.count()).select_from(KnowledgeRelation)) == 81
        assert db.scalar(select(func.count()).select_from(DiagnosticQuestion)) == 60


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        (lambda items: items[1].update(knowledge_id=items[0]["knowledge_id"]), "duplicate"),
        (lambda items: items[0].update(source_title=""), "source_title"),
        (lambda items: items[0].update(content="too short"), "at least 120 characters"),
        (lambda items: items[0].pop("source_url"), "source_url"),
        (lambda items: items[0].update(source_url="relative/path"), "source_url"),
        (
            lambda items: items[0].update(license_note="project-internal; team-authored"),
            "project-internal",
        ),
        (
            lambda items: items[0].update(content=items[0]["content"] + "本项目规则"),
            "project-specific content",
        ),
        (
            lambda items: items[0].update(knowledge_id="demo_script_design"),
            "retired knowledge",
        ),
        (lambda items: items[0].update(prerequisites=[items[0]["knowledge_id"]]), "self"),
        (lambda items: items[0].update(related=["unknown_knowledge"]), "invalid relation"),
        (lambda items: items[0].update(related=[[]]), "non-empty string IDs"),
    ],
)
def test_invalid_seed_data_is_rejected(mutation, expected_error: str) -> None:
    items = load_knowledge_items()
    mutation(items)

    with pytest.raises(SeedValidationError, match=expected_error):
        validate_knowledge_items(
            items,
            expected_prerequisites=sum(len(item.get("prerequisites", [])) for item in items),
            expected_related=sum(len(item.get("related", [])) for item in items),
        )


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        (
            lambda questions: questions[1].update(question_id=questions[0]["question_id"]),
            "duplicate question_id",
        ),
        (
            lambda questions: questions[0].update(knowledge_id="unknown_knowledge"),
            "invalid diagnostic knowledge references",
        ),
        (lambda questions: questions[0].update(stem=""), "stem"),
        (
            lambda questions: questions[0].update(options=["same", "same"]),
            "options",
        ),
        (
            lambda questions: questions[0].update(answer_key={"correct_option": 99}),
            "correct_option",
        ),
        (
            lambda questions: questions[-1].update(answer_key={"rubric": []}),
            "rubric",
        ),
    ],
)
def test_invalid_diagnostic_questions_are_rejected(mutation, expected_error: str) -> None:
    items = load_knowledge_items()
    questions = load_diagnostic_questions()
    mutation(questions)

    with pytest.raises(SeedValidationError, match=expected_error):
        validate_diagnostic_questions(
            questions,
            knowledge_ids={item["knowledge_id"] for item in items},
        )
