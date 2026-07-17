from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import GenerationTask, GraphCheckpoint, ManualReviewTask
from app.schemas.common import ApiResponse, ok
from app.workers.generation_worker import run_generation_task

router = APIRouter()
DECISIONS = {"approve", "request_revision", "reject"}


def _serialize(item: ManualReviewTask, task: GenerationTask) -> dict[str, Any]:
    return {
        "manual_review_id": item.public_id,
        "task_id": task.public_id,
        "trigger_reason": item.trigger_reason,
        "status": item.status,
        "decision": item.decision,
        "review_comment": item.review_comment,
        "reviewed_by": item.reviewed_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@router.get("", response_model=ApiResponse)
def list_manual_reviews(
    status: str | None = Query(None), db: Session = Depends(get_db)
) -> ApiResponse:
    statement = (
        select(ManualReviewTask, GenerationTask)
        .join(GenerationTask, GenerationTask.id == ManualReviewTask.task_id)
        .order_by(ManualReviewTask.created_at.desc())
    )
    if status:
        statement = statement.where(ManualReviewTask.status == status)
    return ok([_serialize(item, task) for item, task in db.execute(statement)])


@router.get("/{review_id}", response_model=ApiResponse)
def get_manual_review(review_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    row = db.execute(
        select(ManualReviewTask, GenerationTask)
        .join(GenerationTask, GenerationTask.id == ManualReviewTask.task_id)
        .where(ManualReviewTask.public_id == review_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Manual review not found")
    return ok(_serialize(row[0], row[1]))


@router.post("/{review_id}/decision", response_model=ApiResponse)
def decide_manual_review(
    review_id: str,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> ApiResponse:
    item = db.scalar(
        select(ManualReviewTask).where(ManualReviewTask.public_id == review_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Manual review not found")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail="Manual review has already been resolved")
    decision = str((payload or {}).get("decision") or "")
    if decision not in DECISIONS:
        raise HTTPException(status_code=422, detail="unsupported manual review decision")
    task = db.get(GenerationTask, item.task_id)
    if task is None or task.status != "waiting_human":
        raise HTTPException(status_code=409, detail="Generation task is not waiting for review")
    checkpoint = db.scalar(
        select(GraphCheckpoint).where(GraphCheckpoint.task_id == task.public_id)
    )
    if checkpoint is None or not (checkpoint.state_json or {}).get("native_checkpoint"):
        raise HTTPException(status_code=409, detail="No resumable checkpoint found")
    review_comment = str((payload or {}).get("comment") or "")[:2000]
    checkpoint.status = "resuming"
    item.status = "resolved"
    item.decision = decision
    item.review_comment = review_comment
    item.reviewed_by = str((payload or {}).get("reviewed_by") or "demo_admin")[:64]
    db.commit()
    background_tasks.add_task(run_generation_task, task.public_id)
    return ok(
        {
            **_serialize(item, task),
            "resume_thread_id": task.public_id,
            "resume_status": "scheduled",
        }
    )
