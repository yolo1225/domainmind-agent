from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Feedback, GenerationTask, Learner, LearnerProfile, LearningResource
from app.services.profile_service import public_id


RECOMMENDED_ACTIONS = {
    "too_hard": "explain",
    "too_easy": "challenge",
    "confusing": "explain",
    "incorrect": "review",
    "has_error": "review",
    "helpful": "no_change",
}


def decide_feedback_action(feedback_type: str) -> str:
    return RECOMMENDED_ACTIONS.get(feedback_type, "no_change")


def create_feedback_task(
    db: Session,
    *,
    learner: Learner,
    profile: LearnerProfile,
    resource: LearningResource,
    feedback: Feedback,
    resource_types: list[str] | None = None,
) -> GenerationTask:
    task = GenerationTask(
        public_id=public_id("task"),
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code="ai_app_dev",
        status="pending",
        resource_types_json=resource_types or [resource.resource_type],
        revision_count=0,
        decision="pending",
        trigger_type="resource_feedback",
        execution_mode="auto",
        learning_goal=f"根据资源 {resource.public_id} 的反馈执行辅导或复核",
        source_resource_id=resource.id,
        source_feedback_id=feedback.id,
        progress=0,
    )
    db.add(task)
    db.flush()
    return task


def record_quick_feedback(
    db: Session,
    *,
    learner: Learner,
    profile: LearnerProfile,
    resource: LearningResource,
    feedback_type: str,
    rating: int | None,
    comment: str,
) -> tuple[Feedback, GenerationTask | None]:
    action = decide_feedback_action(feedback_type)
    feedback = Feedback(
        resource_id=resource.id,
        learner_id=learner.id,
        rating=rating,
        feedback_type="text_selection" if feedback_type in {"incorrect", "has_error"} else "quick_tag",
        feedback_summary_json={"tag": feedback_type, "comment_summary": comment[:120]},
        triggered_action=action,
        comment=comment[:2000],
        feedback_intent="incorrect" if feedback_type == "has_error" else feedback_type,
        recommended_action=action,
        profile_update_required=False,
        profile_change_evidence_json=[{"type": "quick_feedback", "value": feedback_type}],
        decision_confidence=0.35,
        decision_reason="快捷标签或评分仅作为辅助证据，不直接修改能力画像",
    )
    db.add(feedback)
    db.flush()
    task = None
    if action == "review":
        task = create_feedback_task(
            db,
            learner=learner,
            profile=profile,
            resource=resource,
            feedback=feedback,
            resource_types=[resource.resource_type],
        )
    return feedback, task


def serialize_feedback_decision(feedback: Feedback, task: GenerationTask | None) -> dict[str, Any]:
    return {
        "feedback_id": str(feedback.id),
        "resource_id": str(feedback.resource_id),
        "feedback_status": "accepted",
        "feedback_intent": feedback.feedback_intent,
        "recommended_action": feedback.recommended_action,
        "profile_update_required": feedback.profile_update_required,
        "decision_reason": feedback.decision_reason,
        "affected_knowledge_ids": feedback.affected_knowledge_ids_json or [],
        "affected_path_node_ids": feedback.affected_path_node_ids_json or [],
        "affected_resource_ids": feedback.affected_resource_ids_json or [],
        "task_id": task.public_id if task else None,
    }
