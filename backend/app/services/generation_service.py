from app.agents.orchestrator import create_initial_state
from app.agents.state import AgentGraphState
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

    for draft in state.get("draft_resources", []):
        report = next(
            (
                item
                for item in state.get("review_reports", [])
                if item.get("resource_type") == draft["resource_type"]
            ),
            {},
        )
        resource = LearningResource(
            public_id=f"res_{task.public_id}_{draft['resource_type']}",
            generation_task_id=task.id,
            resource_type=draft["resource_type"],
            title=draft["title"],
            content_md=draft["content"],
            difficulty=draft["difficulty"],
            learner_profile_type=profile_payload.get("profile_type", ""),
            sources_json=draft["sources"],
            version=1,
            review_status=_review_status(report),
        )
        db.add(resource)
        db.flush()

        db.add(
            ReviewReport(
                resource_id=resource.id,
                primary_review_json={
                    "score": report.get("overall_score", 0),
                    "factual_accuracy": report.get(
                        "factual_accuracy", report.get("facts_score", 0)
                    ),
                    "source_traceability": report.get(
                        "source_traceability", report.get("source_traceability_score", 0)
                    ),
                    "difficulty_match": report.get(
                        "difficulty_match", report.get("difficulty_match_score", 0)
                    ),
                    "core_knowledge_coverage": report.get(
                        "core_knowledge_coverage", report.get("coverage_score", 0)
                    ),
                    "review_notes": report.get("review_notes", []),
                },
                secondary_review_json={
                    "score": report.get("overall_score", 0),
                    "factual_accuracy": report.get(
                        "factual_accuracy", report.get("facts_score", 0)
                    ),
                    "source_traceability": report.get(
                        "source_traceability", report.get("source_traceability_score", 0)
                    ),
                    "difficulty_match": report.get(
                        "difficulty_match", report.get("difficulty_match_score", 0)
                    ),
                    "core_knowledge_coverage": report.get(
                        "core_knowledge_coverage", report.get("coverage_score", 0)
                    ),
                },
                arbitration_json={
                    "required": False,
                    "reason": "mvp_rule_based_review_v1",
                    "failure_level": report.get("failure_level", "none"),
                    "revision_required": report.get("revision_required", False),
                },
                manual_review_required=False,
                passed=bool(report.get("passed")),
            )
        )
