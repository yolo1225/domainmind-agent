from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.tutoring_agent import TutoringAgent
from app.models import (
    Feedback,
    GenerationTask,
    Learner,
    LearnerProfile,
    LearningResource,
    TutoringMessage,
    TutoringSession,
)
from app.services.feedback_service import create_feedback_task
from app.services.profile_service import public_id


def create_session(
    db: Session, *, learner: Learner, resource: LearningResource | None
) -> TutoringSession:
    if resource is None:
        raise ValueError("P0 tutoring sessions must be attached to a learning resource")
    session = TutoringSession(
        public_id=public_id("tutor"),
        learner_id=learner.id,
        resource_id=resource.id,
        status="active",
        turn_count=0,
    )
    db.add(session)
    db.flush()
    return session


def add_learner_message(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
    content: str,
    evidence: list[dict] | None = None,
) -> tuple[TutoringMessage, TutoringMessage, Feedback, GenerationTask | None, dict]:
    if session.status != "active":
        raise ValueError("tutoring session is not active")
    resource = db.get(LearningResource, session.resource_id) if session.resource_id else None
    learner = db.get(Learner, session.learner_id)
    if learner is None:
        raise ValueError("learner not found")
    if resource is None:
        raise ValueError("tutoring session resource not found")

    learner_message = TutoringMessage(
        public_id=public_id("msg"),
        session_id=session.id,
        sender="learner",
        message_type="question",
        content=content,
    )
    db.add(learner_message)
    db.flush()
    session.turn_count += 1
    previous_feedback = db.scalar(
        select(Feedback)
        .where(Feedback.tutoring_session_id == session.id)
        .order_by(Feedback.id.desc())
    )
    source_ids = [
        str(item.get("knowledge_id"))
        for item in (resource.sources_json or [])
        if isinstance(item, dict) and item.get("knowledge_id")
    ]
    output = TutoringAgent().execute(
        {
            "feedback_text": content,
            "tutoring_turn_count": session.turn_count,
            "profile_change_evidence": evidence or [],
            "previous_feedback_intent": previous_feedback.feedback_intent if previous_feedback else None,
        }
    )
    action = output["recommended_action"]
    if session.turn_count == 1 and action in {"explain", "challenge"}:
        action = "no_change"
    verification_evidence: list[dict] = []
    if (
        session.turn_count >= 2
        and previous_feedback
        and previous_feedback.feedback_intent in {"too_easy", "too_hard", "confusing"}
        and len(content) >= 20
    ):
        verification_evidence = [
            {
                "type": "validated_behavior",
                "summary": "follow-up tutoring response supplied after a verification prompt",
                "knowledge_id": knowledge_id,
                "confidence": 0.75,
                "confirmed": True,
            }
            for knowledge_id in source_ids[:8]
        ]
    all_evidence = [*output.get("evidence", []), *(evidence or []), *verification_evidence]
    feedback = Feedback(
        resource_id=resource.id,
        learner_id=learner.id,
        rating=None,
        feedback_type="tutoring_message",
        feedback_summary_json={"message_summary": content[:120]},
        triggered_action=action,
        comment=content[:2000],
        tutoring_session_id=session.id,
        tutoring_message_id=learner_message.id,
        feedback_intent=output["feedback_intent"],
        recommended_action=action,
        profile_update_required=False,
        profile_change_evidence_json=all_evidence,
        decision_confidence=0.75 if verification_evidence else (0.45 if not evidence else 0.75),
        decision_reason=output["decision_reason"],
    )
    db.add(feedback)
    db.flush()
    learner_message.feedback_id = feedback.id
    reply = TutoringMessage(
        public_id=public_id("msg"),
        session_id=session.id,
        sender="tutoring_agent",
        message_type="hint" if session.turn_count == 1 else "explanation",
        content=output["reply"],
        feedback_id=feedback.id,
    )
    db.add(reply)
    db.flush()

    task = None
    if resource and action in {"review", "challenge", "explain"}:
        task = create_feedback_task(
            db,
            learner=learner,
            profile=profile,
            resource=resource,
            feedback=feedback,
            resource_types=[resource.resource_type],
        )
    return learner_message, reply, feedback, task, output


def serialize_session(db: Session, session: TutoringSession) -> dict:
    messages = list(
        db.scalars(
            select(TutoringMessage)
            .where(TutoringMessage.session_id == session.id)
            .order_by(TutoringMessage.id)
        )
    )
    return {
        "session_id": session.public_id,
        "status": session.status,
        "turn_count": session.turn_count,
        "messages": [
            {
                "message_id": item.public_id,
                "sender": item.sender,
                "message_type": item.message_type,
                "content": item.content,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in messages
        ],
    }
