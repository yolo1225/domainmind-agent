from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.common import ApiResponse, ok
from app.services.diagnostic_service import create_diagnostic_session, submit_diagnostic_session

router = APIRouter()


@router.post("/sessions", response_model=ApiResponse)
def create_session(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> ApiResponse:
    payload = payload or {}
    return ok(
        create_diagnostic_session(
            db,
            learner_id=payload.get("learner_id", "learner_001"),
            domain_code=payload.get("domain_code", "ai_app_dev"),
            question_count=payload.get("question_count", 10),
        )
    )


@router.post("/sessions/{session_id}/submit", response_model=ApiResponse)
def submit_session(
    session_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> ApiResponse:
    return ok(
        submit_diagnostic_session(
            db,
            session_id=session_id,
            learner_id=payload.get("learner_id", "learner_001"),
            domain_code=payload.get("domain_code", "ai_app_dev"),
            answers=payload.get("answers", []),
        )
    )
