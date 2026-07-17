from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import GenerationTask, Learner, LearningResource
from app.schemas.common import ApiResponse, ok
from app.services.demo_flow_service import serialize_resource
from app.services.feedback_service import record_quick_feedback, serialize_feedback_decision
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import default_profile_for_learner
from app.services.resource_export_service import export_resource, resolve_export_path
from app.workers.generation_worker import run_generation_task

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_resources(
    include_unpublished: bool = Query(False, description="Administrator view"),
    db: Session = Depends(get_db),
) -> ApiResponse:
    statement = (
        select(LearningResource, GenerationTask)
        .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
        .order_by(GenerationTask.created_at.desc(), LearningResource.id.asc())
        .limit(100)
    )
    if not include_unpublished:
        statement = statement.where(
            LearningResource.is_current.is_(True),
            LearningResource.review_status == "passed",
        )
    rows = list(db.execute(statement))
    return ok([serialize_resource(resource, task) for resource, task in rows])


@router.post("/{resource_id}/feedback", response_model=ApiResponse)
def submit_resource_feedback(
    resource_id: str,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> ApiResponse:
    payload = payload or {}
    allowed_types = {
        "too_hard", "too_easy", "confusing", "incorrect", "has_error", "helpful"
    }
    feedback_type = str(payload.get("feedback_type", "confusing"))
    if feedback_type not in allowed_types:
        raise HTTPException(status_code=422, detail="unsupported quick feedback type")
    learner = get_or_create_demo_learner(db, payload.get("learner_id", "learner_001"))
    resource = db.scalar(
        select(LearningResource).where(LearningResource.public_id == resource_id)
    )
    if resource is None:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    profile = default_profile_for_learner(db, learner)
    feedback, task = record_quick_feedback(
        db,
        learner=learner,
        profile=profile,
        resource=resource,
        feedback_type=feedback_type,
        rating=payload.get("rating"),
        comment=str(payload.get("selected_text") or payload.get("comment") or ""),
    )
    db.commit()
    if task:
        background_tasks.add_task(run_generation_task, task.public_id)
    result = serialize_feedback_decision(feedback, task)
    result["resource_id"] = resource.public_id
    return ok(result)


@router.get("/{resource_id}/versions", response_model=ApiResponse)
def list_resource_versions(resource_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    resource = db.scalar(
        select(LearningResource).where(LearningResource.public_id == resource_id)
    )
    if resource is None:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    series_id = resource.series_id or resource.public_id
    versions = list(
        db.scalars(
            select(LearningResource)
            .where(LearningResource.series_id == series_id)
            .order_by(LearningResource.version.desc())
        )
    )
    return ok(
        [
            {
                "resource_id": item.public_id,
                "series_id": series_id,
                "version": item.version,
                "is_current": item.is_current,
                "review_status": item.review_status,
                "adaptation_reason": item.adaptation_reason,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in versions
        ]
    )


@router.post("/{resource_id}/export", response_model=ApiResponse)
def create_resource_export(
    resource_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> ApiResponse:
    resource = db.scalar(
        select(LearningResource).where(LearningResource.public_id == resource_id)
    )
    if resource is None:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    if resource.review_status != "passed":
        raise HTTPException(status_code=409, detail="unapproved resource cannot be exported")
    try:
        export_payload = payload or {}
        return ok(
            export_resource(
                db,
                resource,
                str(export_payload.get("format", "markdown")),
                str(export_payload.get("audience", "learner")),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/exports/{file_name}", include_in_schema=False)
def download_resource_export(file_name: str) -> FileResponse:
    try:
        path = resolve_export_path(file_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="export not found") from exc
    return FileResponse(path, filename=path.name)
