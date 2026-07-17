from app.agents.orchestrator import create_initial_state
from app.agents.legacy_state import AgentGraphState
from app.models import GenerationTask, LearnerProfile, LearningResource, ReviewReport


def _review_status(report: dict) -> str:
    if report.get("passed"):
        return "passed"
    if report.get("failure_level") == "failed":
        return "failed"
    return "revision_required"


def preview_generation_state(task_id: str, learner_id: str, profile_id: str, learning_goal: str):
    return create_initial_state(task_id, learner_id, profile_id, learning_goal)


def persist_generated_resources(
    db,
    task: GenerationTask,
    profile: LearnerProfile,
    state: AgentGraphState,
) -> None:
    profile_payload = profile.ability_profile_json or {}
    existing_count = (
        db.query(LearningResource)
        .filter(LearningResource.generation_task_id == task.id)
        .count()
    )
    if existing_count:
        return

    source_resource = db.get(LearningResource, task.source_resource_id) if task.source_resource_id else None
    for draft in state.get("draft_resources", []):
        report = next(
            (
                item
                for item in state.get("review_reports", [])
                if item.get("resource_type") == draft["resource_type"]
            ),
            {},
        )
        previous = (
            source_resource
            if source_resource is not None
            and source_resource.resource_type == draft["resource_type"]
            else None
        )
        version = (previous.version + 1) if previous else 1
        series_id = (previous.series_id or previous.public_id) if previous else ""
        human_approved = state.get("human_review_decision") == "approve"
        resource = LearningResource(
            public_id=f"res_{task.public_id}_{draft['resource_type']}_v{version}",
            generation_task_id=task.id,
            resource_type=draft["resource_type"],
            title=draft["title"],
            content_md=draft["content"],
            difficulty=draft["difficulty"],
            learner_profile_type=profile_payload.get("profile_type", ""),
            sources_json=draft["sources"],
            version=version,
            review_status="passed" if human_approved else _review_status(report),
            series_id=series_id,
            previous_resource_id=previous.id if previous else None,
            is_current=True,
            adaptation_reason=state.get("decision_reason")
            or f"基于画像 {profile.public_id} 和检索来源生成",
        )
        db.add(resource)
        db.flush()
        if not resource.series_id:
            resource.series_id = resource.public_id
        if previous:
            previous.is_current = False

        db.add(
            ReviewReport(
                resource_id=resource.id,
                task_id=task.id,
                primary_review_json=report.get("primary_review", {}),
                secondary_review_json=report.get("secondary_review", {}),
                arbitration_json=report.get("arbitration", {}),
                manual_review_required=False,
                passed=human_approved or bool(report.get("passed")),
                factual_score=float(report.get("factual_accuracy", 0)),
                source_trace_score=float(report.get("source_traceability", 0)),
                difficulty_match_score=float(report.get("difficulty_match", 0)),
                coverage_score=float(report.get("core_knowledge_coverage", 0)),
                decision="passed" if human_approved else report.get("decision", "passed"),
                evidence_refs_json=[
                    item.get("knowledge_id") for item in (draft.get("sources") or [])
                ],
                disagreement_summary_json=(report.get("arbitration") or {}).get(
                    "initial_scores", {}
                ),
                review_rule_version="review-v1",
                issues_json=report.get("review_notes", []),
                suggestions_json=[],
            )
        )
