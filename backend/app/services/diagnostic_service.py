from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.nodes import load_profile
from app.agents.state import AgentGraphState
from app.models import AgentMessageRecord, AgentRun, DiagnosticQuestion
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import public_id

PROFILE_AGENT_NAME = "profile_analysis_agent"


def _question_payload(question: DiagnosticQuestion) -> dict[str, Any]:
    return {
        "question_id": question.public_id,
        "knowledge_id": question.knowledge_item_id,
        "question_type": question.question_type,
        "stem": question.stem,
        "options": question.options_json or [],
        "difficulty": question.difficulty,
    }


def _message(
    db: Session,
    *,
    session_id: str,
    message_type: str,
    payload: dict[str, Any],
) -> None:
    db.add(
        AgentMessageRecord(
            session_id=session_id,
            task_id=session_id,
            sender=PROFILE_AGENT_NAME,
            receiver="orchestrator_agent",
            message_type=message_type,
            payload_summary_json=payload,
        )
    )


def create_diagnostic_session(
    db: Session,
    *,
    learner_id: str = "learner_001",
    domain_code: str = "ai_app_dev",
    question_count: int = 10,
) -> dict[str, Any]:
    learner = get_or_create_demo_learner(db, learner_id)
    questions = list(
        db.scalars(
            select(DiagnosticQuestion)
            .where(DiagnosticQuestion.domain_code == domain_code)
            .order_by(DiagnosticQuestion.difficulty, DiagnosticQuestion.public_id)
            .limit(question_count)
        )
    )
    return {
        "session_id": public_id("diag"),
        "learner_id": learner.public_id,
        "domain_code": domain_code,
        "question_count": len(questions),
        "status": "created",
        "questions": [_question_payload(question) for question in questions],
    }


def submit_diagnostic_session(
    db: Session,
    *,
    session_id: str,
    learner_id: str = "learner_001",
    domain_code: str = "ai_app_dev",
    answers: list[dict[str, Any]],
) -> dict[str, Any]:
    learner = get_or_create_demo_learner(db, learner_id)
    answer_by_question_id = {item["question_id"]: item.get("answer") for item in answers}
    question_ids = list(answer_by_question_id.keys())
    questions = list(
        db.scalars(select(DiagnosticQuestion).where(DiagnosticQuestion.public_id.in_(question_ids)))
    )

    started_at = time.perf_counter()
    run = AgentRun(
        generation_task_id=None,
        agent_name=PROFILE_AGENT_NAME,
        status="running",
        input_summary_json={
            "session_id": session_id,
            "learner_id": learner.public_id,
            "domain_code": domain_code,
            "profile_mode": "analyze_diagnostic",
            "question_count": len(questions),
            "question_ids": question_ids,
        },
        output_summary_json={},
        llm_calls=0,
        tokens_used=0,
        duration_ms=0,
    )
    db.add(run)
    _message(
        db,
        session_id=session_id,
        message_type="command",
        payload={
            "session_id": session_id,
            "learner_id": learner.public_id,
            "status": "running",
            "question_count": len(questions),
        },
    )
    db.flush()

    try:
        state: AgentGraphState = {
            "db_session": db,
            "session_id": session_id,
            "learner_id": learner.public_id,
            "domain_code": domain_code,
            "profile_mode": "analyze_diagnostic",
            "answers": answers,
            "question_ids": question_ids,
            "answer_by_question_id": answer_by_question_id,
            "agent_trace": [],
        }
        state = load_profile(state)
        result = state["profile_result"]
        output_summary = {
            "session_id": session_id,
            "learner_id": learner.public_id,
            "profile_id": result["profile_id"],
            "profile_type": result["profile_type"],
            "score": result["score"],
            "weak_knowledge_count": len(result.get("weak_knowledge", [])),
            "learning_path_id": result["learning_path_id"],
            "evidence_question_count": len(questions),
        }
        run.status = "completed"
        run.output_summary_json = output_summary
        run.duration_ms = round((time.perf_counter() - started_at) * 1000)
        _message(
            db,
            session_id=session_id,
            message_type="result",
            payload={**output_summary, "status": "completed"},
        )
        db.commit()
        return {
            **result,
            "agent_run_id": run.id,
            "agent_name": PROFILE_AGENT_NAME,
        }
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.output_summary_json = {"session_id": session_id, "error": str(exc)}
        run.duration_ms = round((time.perf_counter() - started_at) * 1000)
        _message(
            db,
            session_id=session_id,
            message_type="error",
            payload={"session_id": session_id, "status": "failed", "error": str(exc)},
        )
        db.commit()
        raise
