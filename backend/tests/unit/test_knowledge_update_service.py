from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    GenerationTask,
    KnowledgeItem,
    KnowledgeRelation,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
)
from app.services.knowledge_update_service import mark_affected_content, related_knowledge_ids


def test_knowledge_impact_marks_only_referencing_paths_and_resources() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        prerequisite = KnowledgeItem(
            public_id="knowledge_a",
            domain_code="ai_app_dev",
            name="A",
            category="test",
            content_md="content a",
            source_title="source",
            license_note="test",
        )
        changed = KnowledgeItem(
            public_id="knowledge_b",
            domain_code="ai_app_dev",
            name="B",
            category="test",
            content_md="content b",
            source_title="source",
            license_note="test",
        )
        db.add_all([prerequisite, changed])
        db.flush()
        db.add(
            KnowledgeRelation(
                source_item_id=prerequisite.id,
                target_item_id=changed.id,
                relation_type="prerequisite",
            )
        )
        learner = Learner(public_id="learner_impact", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_impact",
            learner_id=learner.id,
            ability_profile_json={},
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
        db.add_all(
            [
                LearningPath(
                    public_id="path_affected",
                    learner_id=learner.id,
                    profile_id=profile.id,
                    domain_code="ai_app_dev",
                    path_json={"stages": [{"knowledge_ids": ["knowledge_b"]}]},
                ),
                LearningPath(
                    public_id="path_unaffected",
                    learner_id=learner.id,
                    profile_id=profile.id,
                    domain_code="ai_app_dev",
                    path_json={"stages": [{"knowledge_ids": ["knowledge_c"]}]},
                ),
            ]
        )
        task = GenerationTask(
            public_id="task_impact",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            resource_types_json=["lecture"],
        )
        db.add(task)
        db.flush()
        db.add_all(
            [
                LearningResource(
                    public_id="resource_affected",
                    generation_task_id=task.id,
                    resource_type="lecture",
                    title="affected",
                    content_md="content",
                    sources_json=[{"knowledge_id": "knowledge_a"}],
                    review_status="passed",
                    is_current=True,
                ),
                LearningResource(
                    public_id="resource_unaffected",
                    generation_task_id=task.id,
                    resource_type="lecture",
                    title="unaffected",
                    content_md="content",
                    sources_json=[{"knowledge_id": "knowledge_c"}],
                    review_status="passed",
                    is_current=True,
                ),
            ]
        )
        db.flush()

        affected_ids = related_knowledge_ids(db, changed)
        impact = mark_affected_content(
            db,
            domain_code="ai_app_dev",
            affected_knowledge_ids=affected_ids,
            reason="test_update",
        )
        db.commit()

        assert affected_ids == {"knowledge_a", "knowledge_b"}
        assert impact == {"learning_paths": 1, "resources": 1}
        paths = list(db.scalars(select(LearningPath).order_by(LearningPath.public_id)))
        resources = list(db.scalars(select(LearningResource).order_by(LearningResource.public_id)))
        assert [path.needs_refresh for path in paths] == [True, False]
        assert [resource.review_status for resource in resources] == ["review_stale", "passed"]
