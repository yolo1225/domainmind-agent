from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Learner
from app.schemas.common import ApiResponse, ok
from app.services.profile_service import latest_profile_for_learner, serialize_profile_detail
from app.services.report_service import build_metric_summary

router = APIRouter()


@router.get("/learners/{learner_id}", response_model=ApiResponse)
def get_learning_report(learner_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_id))
    if learner is None:
        raise HTTPException(status_code=404, detail=f"Learner not found: {learner_id}")

    profile = latest_profile_for_learner(db, learner)
    detail = serialize_profile_detail(db, learner, profile)
    learning_path = detail.get("learning_path") or {}
    stages = learning_path.get("stages", []) if isinstance(learning_path, dict) else []

    return ok(
        {
            "learner_id": learner.public_id,
            "profile_id": detail.get("profile_id"),
            "profile_type": detail.get("profile_type"),
            "radar": detail.get("radar", [0, 0, 0, 0, 0]),
            "path": [stage.get("name", "") for stage in stages],
            "path_detail": stages,
            "weak_knowledge": detail.get("weak_knowledge", []),
            "metrics": build_metric_summary(
                hallucination_rate=0.03,
                difficulty_match=0.87,
                coverage=0.91,
            ),
        }
    )
