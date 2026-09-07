import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.v1 import learning_packages as learning_packages_api
from app.agents.contracts import QUALITY_RULE_VERSION
from app.core.security import Principal
from app.models import (
    Base,
    Feedback,
    GenerationTask,
    KnowledgeItem,
    KnowledgeUpdateImpact,
    Learner,
    LearningAdjustmentProposal,
    LearnerProfile,
    LearningPath,
    LearningPackageResource,
    LearningResource,
    ReviewReport,
    TutoringSession,
)
from app.services.generation_service import (
    _compose_published_package,
    recover_misclassified_refresh_task,
)
from app.services.feedback_service import (
    FeedbackSourceCompatibilityError,
    create_feedback_task,
)
from app.services.learning_package_service import (
    ensure_package_members,
    package_member_rows,
    serialize_package,
)
from app.services.learning_adjustment_service import (
    decide_proposal_resource,
    pending_resource_proposals,
)
from app.services.node_mastery_service import affected_resource_types


def _report(resource: LearningResource, task: GenerationTask) -> ReviewReport:
    knowledge_id = f"knowledge_{resource.resource_type}"
    return ReviewReport(
        resource_id=resource.id,
        task_id=task.id,
        primary_review_json={"passed": True},
        secondary_review_json={"passed": True},
        passed=True,
        quality_passed=True,
        decision="passed",
        review_rule_version=QUALITY_RULE_VERSION,
        quality_rule_version=QUALITY_RULE_VERSION,
        verifiable_claim_count=10,
        evaluated_claim_count=10,
        contradicted_claim_count=0,
        evidence_insufficient_claim_count=0,
        unresolved_claim_count=0,
        hallucinated_claim_count=0,
        difficulty_match_score=90,
        target_knowledge_ids_json=[knowledge_id],
        covered_knowledge_ids_json=[knowledge_id],
        covered_core_knowledge_count=1,
        target_core_knowledge_count=1,
        core_knowledge_coverage=100,
    )


def _package_fixture(
    db, resource_types=("lecture", "practice_guide", "graded_quiz")
):
    learner = Learner(public_id="learner_package", target_domain="ai_app_dev")
    db.add(learner)
    db.flush()
    profile = LearnerProfile(
        public_id="profile_package",
        learner_id=learner.id,
        ability_profile_json={},
        weak_knowledge_json=[],
        diagnosis_completed=True,
    )
    db.add(profile)
    db.flush()
    source_task = GenerationTask(
        public_id="task_source",
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code="ai_app_dev",
        status="completed",
        decision="completed",
        learning_goal="[[evaluation_case:V4-EVAL-041]] 反馈任务目标继承验证",
        resource_types_json=list(resource_types),
        is_current_package=True,
        package_quality_json={"quality_rule_version": QUALITY_RULE_VERSION},
    )
    db.add(source_task)
    db.flush()
    resources = {}
    for resource_type in resource_types:
        resource = LearningResource(
            public_id=f"resource_{resource_type}_v1",
            generation_task_id=source_task.id,
            resource_type=resource_type,
            title=resource_type,
            content_md="content",
            sources_json=[{"knowledge_id": f"knowledge_{resource_type}"}],
            review_status="passed",
            version=1,
            series_id=f"series_{resource_type}",
            is_current=True,
        )
        db.add(resource)
        db.flush()
        db.add(_report(resource, source_task))
        resources[resource_type] = resource
    ensure_package_members(db, source_task)
    db.flush()
    return learner, profile, source_task, resources


def test_stale_resource_proposal_can_still_be_skipped() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner, profile, _task, resources = _package_fixture(db, ("lecture",))
        path = LearningPath(
            public_id="path_stale_proposal",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="active",
            path_json={"current_node_id": "unit:current", "node_states": {}},
        )
        db.add(path)
        db.flush()
        session = TutoringSession(
            public_id="tutoring_stale_proposal",
            learner_id=learner.id,
            resource_id=resources["lecture"].id,
        )
        db.add(session)
        db.flush()
        proposal = LearningAdjustmentProposal(
            public_id="adjustment_stale_proposal",
            learner_id=learner.id,
            profile_id=profile.id,
            learning_path_id=path.id,
            resulting_profile_id=profile.id,
            resulting_learning_path_id=path.id,
            path_node_id="unit:previous",
            tutoring_session_id=session.id,
            source_resource_id=resources["lecture"].id,
            hypothesis_type="mastery_up",
            status="stale",
            resource_recommendation_json={
                "path_node_id": "unit:previous",
                "resource_types": ["graded_quiz"],
                "decision_type": "challenge",
            },
        )
        db.add(proposal)
        db.commit()

        result, task = decide_proposal_resource(
            db,
            proposal_id=proposal.public_id,
            learner_public_id=learner.public_id,
            decision="skip",
        )

        db.refresh(proposal)
        assert result == {
            "proposal_id": "adjustment_stale_proposal",
            "decision": "skip",
            "task_id": None,
        }
        assert task is None
        assert proposal.status == "resource_skipped"
        assert proposal.resource_decision == "skip"


def test_feedback_refresh_preserves_single_resource_package_scope() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner, profile, source_task, source_resources = _package_fixture(
            db, ("practice_guide",)
        )
        refresh_task = GenerationTask(
            public_id="task_single_feedback",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="running",
            resource_types_json=["practice_guide"],
            source_task_id=source_task.id,
            source_resource_id=source_resources["practice_guide"].id,
            trigger_type="resource_feedback",
            event_type="resource_feedback",
        )
        db.add(refresh_task)
        db.flush()
        generated = LearningResource(
            public_id="resource_practice_guide_v2",
            generation_task_id=refresh_task.id,
            resource_type="practice_guide",
            title="practice guide v2",
            content_md="new content",
            sources_json=[{"knowledge_id": "knowledge_practice_guide"}],
            review_status="passed",
            version=2,
            series_id=source_resources["practice_guide"].series_id,
            previous_resource_id=source_resources["practice_guide"].id,
            is_current=True,
        )
        db.add(generated)
        db.flush()
        db.add(_report(generated, refresh_task))
        db.flush()

        _compose_published_package(db, refresh_task)

        rows = package_member_rows(db, refresh_task)
        assert len(rows) == 1
        assert rows[0][0].membership_type == "generated"
        assert rows[0][1].resource_type == "practice_guide"
        assert refresh_task.is_current_package is True
        assert source_task.is_current_package is False


def test_package_serialization_resolves_knowledge_names_for_existing_resources() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        _learner, _profile, task, _resources = _package_fixture(db, ("lecture",))
        db.add(
            KnowledgeItem(
                public_id="knowledge_lecture",
                domain_code="ai_app_dev",
                name="异步 API 调用",
                category="实操技能",
                difficulty=3,
                tags_json=[],
                content_md="异步调用基础知识。",
                source_title="Python 文档",
                license_note="官方文档",
                status="published",
            )
        )
        db.add(
            KnowledgeItem(
                public_id="knowledge_lecture_duplicate",
                domain_code="ai_app_dev",
                name="异步 API 调用",
                category="实操技能",
                difficulty=3,
                tags_json=[],
                content_md="同一知识点的另一条来源记录。",
                source_title="Python 文档",
                license_note="官方文档",
                status="published",
            )
        )
        _resources["lecture"].sources_json = [
            {"knowledge_id": "knowledge_lecture"},
            {"knowledge_id": "knowledge_lecture"},
            {"knowledge_id": "knowledge_lecture_duplicate"},
        ]
        db.commit()

        payload = serialize_package(db, task)

    assert payload["resources"][0]["source_details"] == [
        {"knowledge_id": "knowledge_lecture", "name": "异步 API 调用"}
    ]


def test_pending_profile_adaptation_keeps_old_package_as_history() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner, original_profile, source_task, resources = _package_fixture(db, ("lecture",))
        updated_profile = LearnerProfile(
            public_id="profile_package_v2",
            learner_id=learner.id,
            domain_code="ai_app_dev",
            ability_profile_json={},
            weak_knowledge_json=[],
            profile_version=2,
            previous_profile_id=original_profile.id,
            diagnosis_completed=True,
            profile_source="feedback_revision",
        )
        db.add(updated_profile)
        db.flush()
        path = LearningPath(
            public_id="path_package_v2",
            learner_id=learner.id,
            profile_id=updated_profile.id,
            domain_code="ai_app_dev",
            status="active",
            path_json={
                "current_node_id": "knowledge:knowledge_lecture",
                "node_states": {
                    "knowledge:knowledge_lecture": {
                        "path_node_id": "knowledge:knowledge_lecture",
                        "knowledge_id": "knowledge_lecture",
                        "title": "当前学习节点",
                        "status": "current",
                    }
                },
            },
        )
        db.add(path)
        db.flush()
        tutoring = TutoringSession(
            public_id="tutoring_package_v2",
            learner_id=learner.id,
            resource_id=resources["lecture"].id,
        )
        db.add(tutoring)
        db.flush()
        proposal = LearningAdjustmentProposal(
            public_id="adjustment_package_v2",
            learner_id=learner.id,
            profile_id=original_profile.id,
            resulting_profile_id=updated_profile.id,
            learning_path_id=path.id,
            resulting_learning_path_id=path.id,
            path_node_id="knowledge:knowledge_lecture",
            tutoring_session_id=tutoring.id,
            source_resource_id=resources["lecture"].id,
            hypothesis_type="support_down",
            status="resource_pending",
            resource_recommendation_json={
                "path_node_id": "knowledge:knowledge_lecture",
                "resource_types": ["lecture"],
                "mode": "remedial",
            },
        )
        db.add(proposal)
        db.flush()

        proposals = pending_resource_proposals(
            db, learner_id=learner.id, domain_code="ai_app_dev"
        )
        package = serialize_package(db, source_task)

    assert proposals[0]["profile_version"] == 2
    assert proposals[0]["previous_profile_version"] == 1
    assert proposals[0]["affected_resources"] == [
        {"resource_id": "resource_lecture_v1", "resource_type": "lecture", "title": "lecture"}
    ]
    assert proposals[0]["route_message"]["reason"] == "GRADED_QUIZ_REQUIRED"
    assert package["profile_adaptation"]["status"] == "pending"
    assert package["profile_adaptation"]["proposal_id"] == "adjustment_package_v2"


def test_partial_refresh_composes_new_package_with_inherited_resource() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner, profile, source_task, source_resources = _package_fixture(db)
        source_task.resource_knowledge_targets_json = {
            "lecture": ["knowledge_lecture"],
            "practice_guide": ["knowledge_practice_guide"],
            "graded_quiz": ["knowledge_lecture", "knowledge_practice_guide"],
        }
        selected_types = affected_resource_types(
            package_task=source_task,
            affected_knowledge_ids=["knowledge_practice_guide"],
            fallback_resource_type="lecture",
        )
        assert selected_types == ["practice_guide", "graded_quiz"]
        refresh_task = GenerationTask(
            public_id="task_refresh",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="running",
            resource_types_json=selected_types,
            source_task_id=source_task.id,
            event_type="knowledge_refresh",
        )
        db.add(refresh_task)
        db.flush()
        impact = KnowledgeUpdateImpact(
            public_id="impact_refresh",
            package_task_id=source_task.id,
            affected_knowledge_ids_json=["knowledge_practice_guide"],
            affected_resource_ids_json=[
                source_resources["practice_guide"].public_id,
                source_resources["graded_quiz"].public_id,
            ],
            status="refreshing",
            resolved_by_task_id=refresh_task.id,
        )
        db.add(impact)
        for resource_type in ("practice_guide", "graded_quiz"):
            resource = LearningResource(
                public_id=f"resource_{resource_type}_v2",
                generation_task_id=refresh_task.id,
                resource_type=resource_type,
                title=f"{resource_type} v2",
                content_md="new content",
                sources_json=[{"knowledge_id": f"knowledge_{resource_type}"}],
                review_status="passed",
                version=2,
                series_id=f"series_{resource_type}",
                previous_resource_id=source_resources[resource_type].id,
                is_current=True,
            )
            db.add(resource)
            db.flush()
            db.add(_report(resource, refresh_task))
        db.flush()

        _compose_published_package(db, refresh_task)
        db.flush()

        rows = list(
            db.execute(
                select(LearningPackageResource, LearningResource)
                .join(LearningResource, LearningResource.id == LearningPackageResource.resource_id)
                .where(LearningPackageResource.package_task_id == refresh_task.id)
                .order_by(LearningPackageResource.sort_order)
            )
        )
        assert [resource.resource_type for _member, resource in rows] == [
            "lecture",
            "practice_guide",
            "graded_quiz",
        ]
        assert [member.membership_type for member, _resource in rows] == [
            "inherited",
            "generated",
            "generated",
        ]
        assert rows[0][1].id == source_resources["lecture"].id
        assert refresh_task.is_current_package is True
        assert source_task.is_current_package is False
        assert impact.status == "resolved"
        assert refresh_task.package_quality_json["passed"] is True
        assert refresh_task.package_quality_json["hallucination_rate"] == 0
        assert refresh_task.package_quality_json["core_knowledge_coverage"] == 100
        assert refresh_task.package_coverage_json["primary_owner"] == {
            "knowledge_lecture": "lecture",
            "knowledge_practice_guide": "practice_guide",
            "knowledge_graded_quiz": "graded_quiz",
        }
        assert set(refresh_task.package_coverage_json["required_knowledge_ids"]) == {
            "knowledge_lecture",
            "knowledge_practice_guide",
            "knowledge_graded_quiz",
        }


def test_package_quality_uses_teaching_resource_coverage_union() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        _learner, _profile, task, resources = _package_fixture(db)
        reports = {
            resource_type: db.scalar(
                select(ReviewReport).where(ReviewReport.resource_id == resource.id)
            )
            for resource_type, resource in resources.items()
        }
        for report in reports.values():
            report.target_knowledge_ids_json = ["k1", "k2", "k3"]
        reports["lecture"].covered_knowledge_ids_json = ["k1", "k2"]
        reports["practice_guide"].covered_knowledge_ids_json = ["k2", "k3"]
        reports["graded_quiz"].covered_knowledge_ids_json = ["k1", "k2", "k3"]
        db.flush()

        _compose_published_package(db, task)
        db.flush()

        assert task.package_quality_json["core_knowledge_coverage"] == 100
        assert task.package_quality_json["passed"] is True
        assert task.package_coverage_json["covered_knowledge_ids"] == [
            "k1",
            "k2",
            "k3",
        ]


def test_profile_feedback_task_composes_complete_package_from_new_profile() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner, original_profile, source_task, source_resources = _package_fixture(db)
        feedback = Feedback(
            resource_id=source_resources["practice_guide"].id,
            learner_id=learner.id,
            feedback_type="too_hard",
            triggered_action="regenerate",
            profile_update_required=True,
        )
        db.add(feedback)
        db.flush()
        task = create_feedback_task(
            db,
            learner=learner,
            profile=original_profile,
            resource=source_resources["practice_guide"],
            feedback=feedback,
            resource_types=["practice_guide"],
        )
        updated_profile = LearnerProfile(
            public_id="profile_package_v2",
            learner_id=learner.id,
            ability_profile_json={"profile_type": "advanced"},
            weak_knowledge_json=[],
            profile_version=2,
            previous_profile_id=original_profile.id,
            diagnosis_completed=True,
            profile_source="feedback_revision",
        )
        db.add(updated_profile)
        db.flush()
        task.profile_id = updated_profile.id
        generated = LearningResource(
            public_id="resource_practice_guide_feedback_v2",
            generation_task_id=task.id,
            resource_type="practice_guide",
            title="practice guide from updated profile",
            content_md="new profile content",
            learner_profile_type="advanced",
            sources_json=[{"knowledge_id": "knowledge_practice_guide"}],
            review_status="passed",
            version=2,
            series_id=source_resources["practice_guide"].series_id,
            previous_resource_id=source_resources["practice_guide"].id,
            is_current=True,
        )
        db.add(generated)
        db.flush()
        db.add(_report(generated, task))
        db.flush()

        _compose_published_package(db, task)
        rows = package_member_rows(db, task)

        assert task.source_task_id == source_task.id
        assert source_task.learning_goal in task.learning_goal
        assert task.event_type == "resource_feedback"
        assert task.profile_id == updated_profile.id
        assert task.is_current_package is True
        assert source_task.is_current_package is False
        assert [resource.resource_type for _member, resource in rows] == [
            "lecture", "practice_guide", "graded_quiz"
        ]
        assert [member.membership_type for member, _resource in rows] == [
            "inherited", "generated", "inherited"
        ]
        assert rows[0][1].id == source_resources["lecture"].id
        assert rows[2][1].id == source_resources["graded_quiz"].id


def test_feedback_task_rejects_v5_source_package_before_partial_regeneration() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner, profile, source_task, resources = _package_fixture(db)
        source_task.package_quality_json = {
            "quality_rule_version": "quality-v5-20260729"
        }
        feedback = Feedback(
            resource_id=resources["lecture"].id,
            learner_id=learner.id,
            feedback_type="has_error",
            triggered_action="review",
        )
        db.add(feedback)
        db.flush()

        with pytest.raises(
            FeedbackSourceCompatibilityError,
            match="V6_FULL_REGENERATION_REQUIRED",
        ):
            create_feedback_task(
                db,
                learner=learner,
                profile=profile,
                resource=resources["lecture"],
                feedback=feedback,
            )

        derived = db.scalar(
            select(GenerationTask).where(GenerationTask.source_feedback_id == feedback.id)
        )
        assert derived is None


def test_package_composition_rejects_incomplete_feedback_source() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner, profile, _source_task, _source_resources = _package_fixture(db)
        task = GenerationTask(
            public_id="task_incomplete_feedback",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="running",
            resource_types_json=["practice_guide"],
            event_type="resource_feedback",
        )
        db.add(task)
        db.flush()
        resource = LearningResource(
            public_id="resource_incomplete_feedback",
            generation_task_id=task.id,
            resource_type="practice_guide",
            title="incomplete",
            content_md="content",
            sources_json=[],
            review_status="passed",
        )
        db.add(resource)
        db.flush()

        with pytest.raises(ValueError, match="published_package_members_incomplete"):
            _compose_published_package(db, task)

        assert task.is_current_package is False


def test_initial_generation_can_publish_requested_resource_subset() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner = Learner(public_id="learner_single", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_single",
            learner_id=learner.id,
            ability_profile_json={},
            weak_knowledge_json=[],
            diagnosis_completed=True,
        )
        db.add(profile)
        db.flush()
        task = GenerationTask(
            public_id="task_single",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="running",
            trigger_type="initial_generation",
            resource_types_json=["lecture"],
        )
        db.add(task)
        db.flush()
        resource = LearningResource(
            public_id="resource_single_lecture",
            generation_task_id=task.id,
            resource_type="lecture",
            title="single lecture",
            content_md="content",
            sources_json=[{"knowledge_id": "knowledge_lecture"}],
            review_status="passed",
        )
        db.add(resource)
        db.flush()
        db.add(_report(resource, task))
        db.flush()

        _compose_published_package(db, task)

        rows = package_member_rows(db, task)
        assert [item.resource_type for _member, item in rows] == ["lecture"]
        assert task.is_current_package is True
        assert task.package_quality_json["passed"] is True


@pytest.mark.parametrize("resource_count", [1, 2, 3])
def test_recover_misclassified_refresh_task_is_atomic_and_idempotent(
    resource_count: int,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner, profile, source_task, source_resources = _package_fixture(db)
        requested_types = ["lecture", "practice_guide", "graded_quiz"][:resource_count]
        refresh_task = GenerationTask(
            public_id=f"task_recover_{resource_count}",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            status="failed",
            progress=95,
            decision="failed",
            resource_types_json=requested_types,
            source_task_id=source_task.id,
            event_type="knowledge_refresh",
            failure_reason="任务缺少可完成决策所需的生成或审核结果。",
            package_coverage_json={"coverage_score": 100, "missing_knowledge_ids": []},
        )
        db.add(refresh_task)
        db.flush()
        impact = KnowledgeUpdateImpact(
            public_id=f"impact_recover_{resource_count}",
            package_task_id=source_task.id,
            affected_resource_ids_json=[
                source_resources[resource_type].public_id for resource_type in requested_types
            ],
            status="pending",
        )
        db.add(impact)
        for resource_type in requested_types:
            previous = source_resources[resource_type]
            resource = LearningResource(
                public_id=f"resource_recovered_{resource_type}_v2",
                generation_task_id=refresh_task.id,
                resource_type=resource_type,
                title=f"{resource_type} v2",
                content_md="recovered content",
                sources_json=[{"knowledge_id": f"knowledge_{resource_type}"}],
                review_status="failed",
                version=2,
                series_id=previous.series_id,
                previous_resource_id=previous.id,
                is_current=False,
            )
            db.add(resource)
            db.flush()
            db.add(_report(resource, refresh_task))
        db.flush()

        recovered = recover_misclassified_refresh_task(db, refresh_task.public_id)
        recovered_again = recover_misclassified_refresh_task(db, refresh_task.public_id)

        rows = package_member_rows(db, recovered)
        assert recovered_again.id == recovered.id
        assert recovered.status == "completed"
        assert recovered.progress == 100
        assert recovered.is_current_package is True
        assert source_task.is_current_package is False
        assert impact.status == "resolved"
        assert len(rows) == 3
        assert {resource.resource_type for _member, resource in rows} == {
            "lecture", "practice_guide", "graded_quiz"
        }
        assert sum(member.membership_type == "generated" for member, _resource in rows) == resource_count
        assert recovered.package_quality_json["passed"] is True
        assert recovered.package_quality_json["hallucination_rate"] == 0
        assert recovered.package_quality_json["core_knowledge_coverage"] == 100


def test_refresh_task_uses_source_package_profile_and_server_impact_scope(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner, profile, source_task, resources = _package_fixture(db)
        impact = KnowledgeUpdateImpact(
            public_id="impact_api",
            package_task_id=source_task.id,
            affected_knowledge_ids_json=["knowledge_practice_guide"],
            affected_resource_ids_json=[resources["practice_guide"].public_id],
            status="pending",
        )
        db.add(impact)
        db.commit()
        monkeypatch.setattr(
            learning_packages_api,
            "require_candidate_rag",
            lambda _domain: {"ready": True},
        )
        result = learning_packages_api.refresh_affected_resources(
            source_task.public_id,
            BackgroundTasks(),
            db,
            Principal("admin", "admin", learner.public_id),
        )
        created = db.scalar(
            select(GenerationTask).where(GenerationTask.public_id == result.data["task_id"])
        )
        assert created is not None
        assert created.profile_id == profile.id
        assert created.source_task_id == source_task.id
        assert created.resource_types_json == ["practice_guide"]
        assert created.event_type == "knowledge_refresh"
