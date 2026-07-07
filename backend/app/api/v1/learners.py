from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Learner
from app.schemas.common import ApiResponse, ok
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import (
    latest_profile_for_learner,
    profile_ability_level,
    serialize_profile_detail,
)

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_learners(db: Session = Depends(get_db)) -> ApiResponse:
    learners = list(db.scalars(select(Learner).order_by(Learner.public_id)))
    if not learners:
        learners = [get_or_create_demo_learner(db, "learner_001")]
        db.commit()

    payload = []
    for learner in learners:
        profile = latest_profile_for_learner(db, learner)
        ability_profile = profile.ability_profile_json if profile else {}
        payload.append(
            {
                "learner_id": learner.public_id,
                "profile_type": ability_profile.get("profile_type", "not_started"),
                "target_domain": learner.target_domain,
                "ability_level": profile_ability_level(ability_profile) if profile else 0,
                "profile_status": "ready" if profile else "not_started",
                "latest_profile_id": profile.public_id if profile else None,
                "updated_at": profile.updated_at.isoformat() if profile else None,
            }
        )
    return ok(payload)


@router.get("/{learner_id}/profile", response_model=ApiResponse)
def get_learner_profile(learner_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_id))
    if learner is None:
        if learner_id == "learner_001":
            learner = get_or_create_demo_learner(db, learner_id)
            db.commit()
        else:
            raise HTTPException(status_code=404, detail=f"Learner not found: {learner_id}")
    return ok(serialize_profile_detail(db, learner))
