from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Learner, LearningResource, TutoringSession
from app.schemas.common import ApiResponse, ok
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import default_profile_for_learner
from app.services.tutoring_service import add_learner_message, create_session, serialize_session
from app.workers.generation_worker import run_generation_task

router = APIRouter()


@router.post("/sessions", response_model=ApiResponse)
def start_tutoring_session(
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> ApiResponse:
    payload = payload or {}
    learner = get_or_create_demo_learner(db, payload.get("learner_id", "learner_001"))
    resource_id = payload.get("resource_id")
    resource = db.scalar(
        select(LearningResource).where(LearningResource.public_id == resource_id)
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="A published resource is required")
    if resource.review_status != "passed" or not resource.is_current:
        raise HTTPException(status_code=409, detail="Only a current passed resource can be tutored")
    session = create_session(db, learner=learner, resource=resource)
    db.commit()
    db.refresh(session)
    return ok(serialize_session(db, session))


@router.post("/sessions/{session_id}/messages", response_model=ApiResponse)
def post_tutoring_message(
    session_id: str,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> ApiResponse:
    session = db.scalar(
        select(TutoringSession).where(TutoringSession.public_id == session_id)
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Tutoring session not found")
    content = str((payload or {}).get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="content is required")
    learner = db.get(Learner, session.learner_id)
    if learner is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    profile = default_profile_for_learner(db, learner)
    try:
        _, reply, feedback, task, output = add_learner_message(
            db,
            session=session,
            profile=profile,
            content=content,
            evidence=list((payload or {}).get("evidence") or []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    if task:
        background_tasks.add_task(run_generation_task, task.public_id)
    return ok(
        {
            "session_id": session.public_id,
            "reply": {
                "message_id": reply.public_id,
                "message_type": reply.message_type,
                "content": reply.content,
            },
            "feedback_intent": output["feedback_intent"],
            "recommended_action": feedback.recommended_action,
            "profile_update_required": feedback.feedback_intent in {"too_hard", "too_easy"}
            and any(
                item.get("type") in {"scored_quiz", "diagnostic_result", "validated_behavior"}
                and (
                    float(item.get("confidence", 0) or 0) >= 0.7
                    or item.get("confirmed") is True
                )
                for item in (feedback.profile_change_evidence_json or [])
                if isinstance(item, dict)
            ),
            "decision_reason": feedback.decision_reason,
            "task_id": task.public_id if task else None,
        }
    )


@router.get("/sessions/{session_id}", response_model=ApiResponse)
def get_tutoring_session(session_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    session = db.scalar(
        select(TutoringSession).where(TutoringSession.public_id == session_id)
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Tutoring session not found")
    return ok(serialize_session(db, session))
