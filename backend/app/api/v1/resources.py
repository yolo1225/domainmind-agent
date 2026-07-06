from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.common import ApiResponse, ok
from app.services.demo_flow_service import list_resources as list_learning_resources
from app.services.demo_flow_service import submit_feedback

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_resources(db: Session = Depends(get_db)) -> ApiResponse:
    return ok(list_learning_resources(db))


@router.post("/{resource_id}/feedback", response_model=ApiResponse)
def submit_resource_feedback(
    resource_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> ApiResponse:
    payload = payload or {}
    try:
        return ok(
            submit_feedback(
                db,
                resource_id=resource_id,
                learner_id=payload.get("learner_id", "learner_001"),
                feedback_type=payload.get("feedback_type", "confusing"),
                rating=payload.get("rating", 3),
                comment=payload.get("comment", ""),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
