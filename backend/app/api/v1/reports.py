from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Feedback, GenerationTask, Learner, LearningPath, LearningResource, ReviewReport
from app.schemas.common import ApiResponse, ok
from app.services.profile_service import latest_profile_for_learner, serialize_profile_detail
from app.services.report_service import build_metric_summary, refresh_learning_path

router = APIRouter()

RESOURCE_TYPE_LABELS = {
    "lecture": "讲义",
    "practice_guide": "实训指导",
    "graded_quiz": "分级测验",
}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _resource_type_counts(resources: list[LearningResource]) -> dict[str, int]:
    counts = {resource_type: 0 for resource_type in RESOURCE_TYPE_LABELS}
    for resource in resources:
        counts[resource.resource_type] = counts.get(resource.resource_type, 0) + 1
    return counts


def _review_status_counts(resources: list[LearningResource]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for resource in resources:
        counts[resource.review_status] = counts.get(resource.review_status, 0) + 1
    return counts


def _source_coverage(resources: list[LearningResource]) -> int:
    source_ids: set[str] = set()
    for resource in resources:
        for source in resource.sources_json or []:
            if isinstance(source, dict):
                source_id = source.get("knowledge_id")
            else:
                source_id = str(source)
            if source_id:
                source_ids.add(str(source_id))
    return len(source_ids)


def _latest_path_for_learner(db: Session, learner: Learner) -> LearningPath | None:
    return db.scalar(
        select(LearningPath)
        .where(LearningPath.learner_id == learner.id)
        .order_by(LearningPath.id.desc())
    )


def _serialize_resource(resource: LearningResource, task: GenerationTask | None) -> dict[str, Any]:
    return {
        "resource_id": resource.public_id,
        "resource_type": resource.resource_type,
        "resource_type_label": RESOURCE_TYPE_LABELS.get(resource.resource_type, resource.resource_type),
        "title": resource.title,
        "difficulty": resource.difficulty,
        "review_status": resource.review_status,
        "source_count": len(resource.sources_json or []),
        "generation_task_id": task.public_id if task else None,
        "generation_status": task.status if task else None,
        "generation_decision": task.decision if task else None,
        "generated_at": _iso(resource.created_at),
    }


def _next_actions(
    *,
    has_profile: bool,
    resources: list[LearningResource],
    feedback_count: int,
    path_needs_refresh: bool,
) -> list[dict[str, str]]:
    if not has_profile:
        return [
            {
                "type": "diagnosis",
                "label": "完成诊断测评",
                "description": "先生成学习者画像，再进入资源生成与反馈闭环。",
                "route": "/diagnostics",
            }
        ]
    if not resources:
        return [
            {
                "type": "generation",
                "label": "生成个性化资源",
                "description": "基于当前画像生成讲义、实训指导和分级测验。",
                "route": "/learners",
            }
        ]
    if feedback_count == 0:
        return [
            {
                "type": "feedback",
                "label": "提交资源反馈",
                "description": "在学习资源页标记太难、太简单、看不懂或内容有误。",
                "route": "/resources",
            }
        ]
    if path_needs_refresh:
        return [
            {
                "type": "path_refresh",
                "label": "刷新学习路径",
                "description": "反馈已触发辅导动作，下一次打开画像或报告时应更新路径。",
                "route": "/reports",
            }
        ]
    return [
        {
            "type": "continue_learning",
            "label": "继续下一轮学习",
            "description": "闭环已完成，可以进入下一轮资源学习或挑战任务。",
            "route": "/resources",
        }
    ]


@router.get("/learners/{learner_id}", response_model=ApiResponse)
def get_learning_report(learner_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_id))
    if learner is None:
        raise HTTPException(status_code=404, detail=f"Learner not found: {learner_id}")

    profile = latest_profile_for_learner(db, learner)
    detail = serialize_profile_detail(db, learner, profile)
    path = _latest_path_for_learner(db, learner)
    path_refresh_performed = False
    if path is not None and path.needs_refresh and profile is not None:
        detail["learning_path"] = refresh_learning_path(
            path=path,
            profile=profile,
            profile_detail=detail,
        )
        db.commit()
        path_refresh_performed = True
    learning_path = detail.get("learning_path") or {}
    stages = learning_path.get("stages", []) if isinstance(learning_path, dict) else []
    path_needs_refresh = bool(path.needs_refresh) if path else False

    resource_rows = list(
        db.execute(
            select(LearningResource, GenerationTask)
            .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
            .where(GenerationTask.learner_id == learner.id)
            .order_by(LearningResource.id.desc())
        )
    )
    resources = [resource for resource, _task in resource_rows]
    recent_resources = [
        _serialize_resource(resource, task)
        for resource, task in resource_rows[:6]
    ]

    review_reports = list(
        db.scalars(
            select(ReviewReport)
            .join(LearningResource, LearningResource.id == ReviewReport.resource_id)
            .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
            .where(GenerationTask.learner_id == learner.id)
            .order_by(ReviewReport.id.desc())
        )
    )
    feedback_rows = list(
        db.execute(
            select(Feedback, LearningResource)
            .join(LearningResource, LearningResource.id == Feedback.resource_id)
            .where(Feedback.learner_id == learner.id)
            .order_by(Feedback.id.desc())
        )
    )
    recent_feedback = [
        {
            "resource_id": resource.public_id,
            "resource_title": resource.title,
            "feedback_type": feedback.feedback_type,
            "rating": feedback.rating,
            "triggered_action": feedback.triggered_action,
            "created_at": _iso(feedback.created_at),
        }
        for feedback, resource in feedback_rows[:5]
    ]
    diagnostic_summary = detail.get("diagnostic_summary", {})
    has_diagnosis = int(diagnostic_summary.get("answer_count") or 0) > 0
    has_profile = detail.get("profile_status") == "ready"
    passed_reviews = sum(1 for report in review_reports if report.passed)
    manual_review_required = sum(1 for report in review_reports if report.manual_review_required)
    reviewed_resource_count = len(review_reports)
    feedback_count = len(feedback_rows)

    return ok(
        {
            "learner_id": learner.public_id,
            "profile_id": detail.get("profile_id"),
            "profile_type": detail.get("profile_type"),
            "radar": detail.get("radar", [0, 0, 0, 0, 0]),
            "path": [stage.get("name", "") for stage in stages],
            "path_detail": stages,
            "weak_knowledge": detail.get("weak_knowledge", []),
            "diagnostic_summary": diagnostic_summary,
            "metrics": build_metric_summary(
                hallucination_rate=0.03,
                difficulty_match=0.87,
                coverage=0.91,
            ),
            "loop_status": {
                "diagnosis": "completed" if has_diagnosis else "pending",
                "profile": "completed" if has_profile else "pending",
                "generation": "completed" if resources else "pending",
                "review": "completed" if reviewed_resource_count else "pending",
                "feedback": "completed" if feedback_count else "pending",
                "path_update": (
                    "refreshed"
                    if path_refresh_performed
                    else "needs_refresh"
                    if path_needs_refresh
                    else "current"
                ),
            },
            "resource_summary": {
                "total": len(resources),
                "by_type": _resource_type_counts(resources),
                "recent": recent_resources,
            },
            "review_summary": {
                "total_reports": reviewed_resource_count,
                "passed": passed_reviews,
                "manual_review_required": manual_review_required,
                "review_status_counts": _review_status_counts(resources),
                "source_coverage": _source_coverage(resources),
            },
            "feedback_summary": {
                "total": feedback_count,
                "latest_action": recent_feedback[0]["triggered_action"] if recent_feedback else None,
                "learning_path_needs_refresh": path_needs_refresh,
                "path_refresh_performed": path_refresh_performed,
                "recent": recent_feedback,
            },
            "next_actions": _next_actions(
                has_profile=has_profile,
                resources=resources,
                feedback_count=feedback_count,
                path_needs_refresh=path_needs_refresh,
            ),
        }
    )
