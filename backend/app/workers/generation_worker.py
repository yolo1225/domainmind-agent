from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from app.agents.nodes import (
    analyze_profile,
    finalize_task,
    generate_resource,
    human_review,
    interpret_feedback,
    prepare_task,
    retrieve_knowledge,
    review_resource,
)
from app.agents.graphs import build_learning_graph
from app.agents.checkpointer import MySQLLangGraphCheckpointer
from app.agents.legacy_state import AgentGraphState
from app.core.db import SessionLocal
from app.models import (
    AgentMessageRecord,
    AgentRun,
    Feedback,
    GenerationTask,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
    ManualReviewTask,
    TutoringMessage,
    TutoringSession,
)
from app.services.profile_service import public_id
from app.services.generation_service import persist_generated_resources

NodeFunc = Callable[[AgentGraphState], AgentGraphState]

NODE_AGENT_NAMES = {
    "prepare_task": "orchestrator_agent",
    "interpret_feedback": "tutoring_agent",
    "analyze_profile": "profile_analysis_agent",
    "retrieve_knowledge": "knowledge_retrieval_agent",
    "generate_resource": "content_generation_agent",
    "review_resource": "review_validation_agent",
    "human_review": "orchestrator_agent",
    "finalize_task": "orchestrator_agent",
}

NODE_FUNCS: dict[str, NodeFunc] = {
    "prepare_task": prepare_task,
    "interpret_feedback": interpret_feedback,
    "analyze_profile": analyze_profile,
    "retrieve_knowledge": retrieve_knowledge,
    "generate_resource": generate_resource,
    "review_resource": review_resource,
    "human_review": human_review,
    "finalize_task": finalize_task,
}

NODE_PROGRESS = {
    "prepare_task": 5,
    "interpret_feedback": 15,
    "analyze_profile": 25,
    "retrieve_knowledge": 40,
    "generate_resource": 60,
    "review_resource": 78,
    "human_review": 82,
    "finalize_task": 95,
}


def _message(
    db: Session,
    *,
    task: GenerationTask,
    sender: str,
    receiver: str = "orchestrator_agent",
    message_type: str = "status",
    payload: dict[str, Any],
) -> None:
    db.add(
        AgentMessageRecord(
            session_id=task.public_id,
            task_id=task.public_id,
            sender=sender,
            receiver=receiver,
            message_type=message_type,
            payload_summary_json=payload,
        )
    )


def _latest_trace_output(state: AgentGraphState, previous_trace_count: int) -> dict[str, Any]:
    trace = state.get("agent_trace", [])
    if len(trace) > previous_trace_count:
        return dict(trace[-1].get("output", {}))
    return {}


def _resource_summary(resource: LearningResource) -> dict[str, Any]:
    return {
        "resource_id": resource.public_id,
        "resource_type": resource.resource_type,
        "title": resource.title,
        "difficulty": resource.difficulty,
        "review_status": resource.review_status,
        "sources": [item.get("knowledge_id") for item in (resource.sources_json or [])],
    }


def _create_profile_version_if_required(
    db: Session,
    *,
    task: GenerationTask,
    profile: LearnerProfile,
    state: AgentGraphState,
) -> LearnerProfile:
    if not state.get("profile_update_required") or state.get("profile_version_created"):
        return profile

    evidence = list(state.get("profile_change_evidence", []))
    changed_dimensions = list(state.get("affected_knowledge_ids", [])) or [
        "evidence_confirmed"
    ]
    next_profile = LearnerProfile(
        public_id=public_id("profile"),
        learner_id=profile.learner_id,
        domain_code=profile.domain_code,
        ability_profile_json=dict(profile.ability_profile_json or {}),
        weak_knowledge_json=list(profile.weak_knowledge_json or []),
        profile_version=int(profile.profile_version or 1) + 1,
        previous_profile_id=profile.id,
        changed_dimensions_json=changed_dimensions,
        evidence_refs_json=evidence,
        confidence=max(
            [float(item.get("confidence", 0)) for item in evidence if isinstance(item, dict)]
            or [0.7]
        ),
        trigger_feedback_id=task.source_feedback_id,
        decision_reason=state.get("decision_reason") or "evidence-supported profile update",
        profile_changed_at=datetime.now(UTC),
    )
    db.add(next_profile)
    db.flush()
    task.profile_id = next_profile.id
    state["profile_id"] = next_profile.public_id
    state["profile_version_created"] = True
    state["profile_version"] = next_profile.profile_version
    for path in db.scalars(
        select(LearningPath).where(LearningPath.learner_id == profile.learner_id)
    ):
        path.needs_refresh = True
    return next_profile


def _initial_state(
    db: Session,
    task: GenerationTask,
    learner: Learner,
    profile: LearnerProfile,
) -> AgentGraphState:
    ability_profile = dict(profile.ability_profile_json or {})
    return {
        "task_id": task.public_id,
        "trigger_type": task.trigger_type,
        "execution_mode": task.execution_mode,
        "learner_id": learner.public_id,
        "profile_id": profile.public_id,
        "profile_mode": "load_existing_profile",
        "domain_code": task.domain_code,
        "resource_types": task.resource_types_json or [],
        "learning_goal": task.learning_goal or "根据诊断结果生成个性化学习资源",
        "profile": {
            **ability_profile,
            "weak_knowledge": profile.weak_knowledge_json or [],
        },
        "retrieved_chunks": [],
        "draft_resources": [],
        "review_reports": [],
        "revision_plan": {},
        "passed_resources": [],
        "revision_count": task.revision_count,
        "decision": "pending",
        "error_message": None,
        "agent_trace": [],
        "profile_update_required": False,
        "profile_change_evidence": [],
        "affected_knowledge_ids": [],
        "affected_path_node_ids": [],
        "affected_resource_ids": [],
        "manual_review_required": False,
        "human_review_decision": None,
        "agent_contexts": {},
    }


def _observable_node(
    *,
    db: Session,
    task: GenerationTask,
    profile: LearnerProfile,
    step: str,
    node_func: NodeFunc,
) -> NodeFunc:
    agent_name = NODE_AGENT_NAMES[step]

    def wrapped(state: AgentGraphState) -> AgentGraphState:
        started_at = time.perf_counter()
        input_summary = {
            "task_id": task.public_id,
            "step": step,
            "resource_types": task.resource_types_json or [],
        }
        if step == "analyze_profile":
            input_summary["profile_mode"] = state.get("profile_mode")
        if state.get("generation_round"):
            input_summary["generation_round"] = state.get("generation_round")

        current_run = AgentRun(
            generation_task_id=task.id,
            agent_name=agent_name,
            status="running",
            input_summary_json=input_summary,
            output_summary_json={"step": step},
            llm_calls=0,
            tokens_used=0,
            duration_ms=0,
        )
        db.add(current_run)
        _message(
            db,
            task=task,
            sender=agent_name,
            payload={"step": step, "status": "running", "task_id": task.public_id},
        )
        db.commit()
        time.sleep(0.2)

        previous_trace_count = len(state.get("agent_trace", []))
        try:
            state["db_session"] = db
            if step == "retrieve_knowledge":
                state["generation_round"] = int(state.get("generation_round") or 0) + 1
            next_state = node_func(state)
            next_state.pop("db_session", None)
            if step == "analyze_profile":
                _create_profile_version_if_required(
                    db, task=task, profile=profile, state=next_state
                )
                if task.source_feedback_id:
                    feedback = db.get(Feedback, task.source_feedback_id)
                    if feedback:
                        feedback.profile_update_required = bool(
                            next_state.get("profile_update_required")
                        )
                        feedback.profile_change_evidence_json = list(
                            next_state.get("profile_change_evidence", [])
                        )
                        feedback.affected_knowledge_ids_json = list(
                            next_state.get("affected_knowledge_ids", [])
                        )
                        feedback.affected_path_node_ids_json = list(
                            next_state.get("affected_path_node_ids", [])
                        )
                        feedback.affected_resource_ids_json = list(
                            next_state.get("affected_resource_ids", [])
                        )
                        feedback.decision_reason = str(
                            next_state.get("decision_reason") or ""
                        )
            if step == "finalize_task" and next_state.get("decision") == "completed":
                active_profile = db.get(LearnerProfile, task.profile_id) or profile
                persist_generated_resources(db, task, active_profile, next_state)
                db.flush()
            output = _latest_trace_output(next_state, previous_trace_count)
            current_run.status = "completed"
            current_run.output_summary_json = {"step": step, **output}
            current_run.duration_ms = round((time.perf_counter() - started_at) * 1000)
            task.progress = max(task.progress, NODE_PROGRESS[step])
            for call in output.get("model_calls", []):
                db.add(
                    AgentRun(
                        generation_task_id=task.id,
                        agent_name=agent_name,
                        status="completed",
                        input_summary_json={
                            "step": step,
                            "model_role": call.get("model_role"),
                            "resource_type": call.get("resource_type"),
                        },
                        output_summary_json={
                            "provider_mode": call.get("provider_mode"),
                            "budget": call.get("budget"),
                        },
                        llm_calls=1,
                        tokens_used=int(call.get("tokens_input", 0))
                        + int(call.get("tokens_output", 0)),
                        tokens_input=int(call.get("tokens_input", 0)),
                        tokens_output=int(call.get("tokens_output", 0)),
                        model_name=call.get("model_name"),
                        prompt_version="v1",
                        duration_ms=int(call.get("duration_ms", 0)),
                    )
                )
            _message(
                db,
                task=task,
                sender=agent_name,
                payload={
                    "step": step,
                    "status": "completed",
                    "task_id": task.public_id,
                    "output": output,
                },
            )
            db.commit()
            return next_state
        except GraphInterrupt:
            state.pop("db_session", None)
            current_run.status = "completed"
            current_run.output_summary_json = {
                "step": step,
                "decision": "manual_review_required",
            }
            current_run.duration_ms = round((time.perf_counter() - started_at) * 1000)
            _message(
                db,
                task=task,
                sender=agent_name,
                message_type="interrupt",
                payload={
                    "step": step,
                    "status": "waiting_human",
                    "task_id": task.public_id,
                },
            )
            db.commit()
            raise
        except Exception as exc:
            state.pop("db_session", None)
            current_run.status = "failed"
            current_run.error_message = str(exc)
            current_run.output_summary_json = {
                **(current_run.output_summary_json or {}),
                "error": str(exc),
            }
            current_run.duration_ms = round((time.perf_counter() - started_at) * 1000)
            _message(
                db,
                task=task,
                sender=agent_name,
                message_type="error",
                payload={"step": step, "status": "failed", "task_id": task.public_id, "error": str(exc)},
            )
            db.commit()
            raise

    return wrapped


def _build_observable_generation_graph(
    db: Session,
    task: GenerationTask,
    profile: LearnerProfile,
    checkpointer: MySQLLangGraphCheckpointer,
):
    overrides = {
        step: _observable_node(
            db=db,
            task=task,
            profile=profile,
            step=step,
            node_func=node_func,
        )
        for step, node_func in NODE_FUNCS.items()
    }
    return build_learning_graph(overrides, checkpointer=checkpointer)


def run_generation_task(task_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
        if task is None:
            return {"task_id": task_id, "status": "not_found"}

        learner = db.get(Learner, task.learner_id)
        profile = db.get(LearnerProfile, task.profile_id)
        if learner is None or profile is None:
            task.status = "failed"
            task.decision = "failed"
            db.commit()
            return {"task_id": task_id, "status": "failed"}

        resume_waiting = task.status == "waiting_human"
        task.status = "running"
        task.decision = "pending"
        db.commit()

        state = _initial_state(db, task, learner, profile)
        checkpointer = MySQLLangGraphCheckpointer(SessionLocal)

        if task.source_feedback_id:
            feedback = db.get(Feedback, task.source_feedback_id)
            if feedback:
                state.update(
                    {
                        "feedback_id": str(feedback.id),
                        "feedback_type": feedback.feedback_type,
                        "feedback_intent": feedback.feedback_intent,
                        "recommended_action": feedback.recommended_action,
                        "feedback_text": feedback.comment,
                        "profile_change_evidence": feedback.profile_change_evidence_json or [],
                    }
                )
                if task.source_resource_id:
                    source_resource = db.get(LearningResource, task.source_resource_id)
                    if source_resource:
                        state["resource_id"] = source_resource.public_id
                        state["affected_resource_ids"] = [source_resource.public_id]
                if feedback.tutoring_session_id:
                    tutoring_session = db.get(TutoringSession, feedback.tutoring_session_id)
                    state["tutoring_session_id"] = (
                        tutoring_session.public_id if tutoring_session else None
                    )
                    state["tutoring_turn_count"] = (
                        tutoring_session.turn_count if tutoring_session else 1
                    )
                if feedback.tutoring_message_id:
                    message = db.get(TutoringMessage, feedback.tutoring_message_id)
                    state["tutoring_message_id"] = message.public_id if message else None

        try:
            graph = _build_observable_generation_graph(db, task, profile, checkpointer)
            graph_input: AgentGraphState | Command = state
            if resume_waiting:
                manual_review = db.scalar(
                    select(ManualReviewTask)
                    .where(ManualReviewTask.task_id == task.id)
                    .where(ManualReviewTask.status == "resolved")
                    .order_by(ManualReviewTask.id.desc())
                )
                if manual_review is None or not manual_review.decision:
                    task.status = "waiting_human"
                    task.decision = "manual_review_required"
                    db.commit()
                    return {"task_id": task.public_id, "status": task.status}
                graph_input = Command(resume=manual_review.decision)
            final_state = graph.invoke(
                graph_input,
                config={"configurable": {"thread_id": task.public_id}},
            )

            task.revision_count = final_state.get("revision_count", 0)
            task.decision = final_state.get("decision", "failed")
            if task.decision in {"completed", "no_change"}:
                task.status = "completed"
                task.progress = 100
                checkpointer.mark_status(task.public_id, "resolved")
            elif task.decision == "manual_review_required":
                task.status = "waiting_human"
                task.progress = max(task.progress, 82)
                checkpointer.mark_status(task.public_id, "waiting_human")
                existing_review = db.scalar(
                    select(ManualReviewTask).where(ManualReviewTask.task_id == task.id)
                )
                if existing_review is None:
                    db.add(
                        ManualReviewTask(
                            public_id=f"mr_{task.public_id}",
                            task_id=task.id,
                            trigger_reason="model_disagreement",
                            status="pending",
                        )
                    )
            elif task.decision == "rejected":
                task.status = "failed"
                checkpointer.mark_status(task.public_id, "resolved")
            else:
                task.status = task.decision
            db.commit()

            resources = list(
                db.scalars(
                    select(LearningResource)
                    .where(LearningResource.generation_task_id == task.id)
                    .order_by(LearningResource.id)
                )
            )
            return {
                "task_id": task.public_id,
                "status": task.status,
                "decision": task.decision,
                "resources": [_resource_summary(resource) for resource in resources],
            }
        except Exception as exc:
            task.status = "failed"
            task.decision = "failed"
            _message(
                db,
                task=task,
                sender="generation_worker",
                message_type="error",
                payload={"task_id": task.public_id, "status": "failed", "error": str(exc)},
            )
            db.commit()
            return {"task_id": task.public_id, "status": "failed", "error": str(exc)}
