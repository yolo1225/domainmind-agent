from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.nodes import (
    decide_next_step,
    generate_resource,
    load_profile,
    persist_resource,
    retrieve_knowledge,
    review_resource,
)
from app.agents.state import AgentGraphState
from app.core.db import SessionLocal
from app.models import (
    AgentMessageRecord,
    AgentRun,
    GenerationTask,
    Learner,
    LearnerProfile,
    LearningResource,
    ReviewReport,
)

NodeFunc = Callable[[AgentGraphState], AgentGraphState]

INITIAL_NODE: tuple[str, str, NodeFunc] = ("load_profile", "profile_analysis_agent", load_profile)

LOOP_NODE_SEQUENCE: list[tuple[str, str, NodeFunc]] = [
    ("retrieve_knowledge", "knowledge_retrieval_agent", retrieve_knowledge),
    ("generate_resource", "content_generation_agent", generate_resource),
    ("review_resource", "review_validation_agent", review_resource),
    ("decide_next_step", "orchestrator_agent", decide_next_step),
]

PERSIST_NODE: tuple[str, str, NodeFunc] = ("persist_resource", "orchestrator_agent", persist_resource)
MAX_GENERATION_ROUNDS = 3


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


def _review_status(report: dict[str, Any]) -> str:
    if report.get("passed"):
        return "passed"
    if report.get("failure_level") == "failed":
        return "failed"
    return "revision_required"


def _run_node(
    db: Session,
    *,
    task: GenerationTask,
    state: AgentGraphState,
    step: str,
    agent_name: str,
    node_func: NodeFunc,
) -> tuple[AgentGraphState, AgentRun, dict[str, Any]]:
    started_at = time.perf_counter()
    input_summary = {
        "task_id": task.public_id,
        "step": step,
        "resource_types": task.resource_types_json or [],
    }
    if step == "load_profile":
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
    state = node_func(state)
    output = _latest_trace_output(state, previous_trace_count)

    current_run.status = "completed"
    current_run.output_summary_json = {"step": step, **output}
    current_run.duration_ms = round((time.perf_counter() - started_at) * 1000)
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
    return state, current_run, output


def _persist_resources(db: Session, task: GenerationTask, profile: LearnerProfile, state: AgentGraphState) -> None:
    profile_payload = profile.ability_profile_json or {}
    for draft in state.get("draft_resources", []):
        report = next(
            (
                item
                for item in state.get("review_reports", [])
                if item.get("resource_type") == draft["resource_type"]
            ),
            {},
        )
        resource = LearningResource(
            public_id=f"res_{time.time_ns()}",
            generation_task_id=task.id,
            resource_type=draft["resource_type"],
            title=draft["title"],
            content_md=draft["content"],
            difficulty=draft["difficulty"],
            learner_profile_type=profile_payload.get("profile_type", ""),
            sources_json=draft["sources"],
            version=1,
            review_status=_review_status(report),
        )
        db.add(resource)
        db.flush()

        db.add(
            ReviewReport(
                resource_id=resource.id,
                primary_review_json={
                    "score": report.get("overall_score", 0),
                    "factual_accuracy": report.get(
                        "factual_accuracy", report.get("facts_score", 0)
                    ),
                    "source_traceability": report.get(
                        "source_traceability", report.get("source_traceability_score", 0)
                    ),
                    "difficulty_match": report.get(
                        "difficulty_match", report.get("difficulty_match_score", 0)
                    ),
                    "core_knowledge_coverage": report.get(
                        "core_knowledge_coverage", report.get("coverage_score", 0)
                    ),
                    "review_notes": report.get("review_notes", []),
                },
                secondary_review_json={
                    "score": report.get("overall_score", 0),
                    "factual_accuracy": report.get(
                        "factual_accuracy", report.get("facts_score", 0)
                    ),
                    "source_traceability": report.get(
                        "source_traceability", report.get("source_traceability_score", 0)
                    ),
                    "difficulty_match": report.get(
                        "difficulty_match", report.get("difficulty_match_score", 0)
                    ),
                    "core_knowledge_coverage": report.get(
                        "core_knowledge_coverage", report.get("coverage_score", 0)
                    ),
                },
                arbitration_json={
                    "required": False,
                    "reason": "mvp_rule_based_review_v1",
                    "failure_level": report.get("failure_level", "none"),
                    "revision_required": report.get("revision_required", False),
                },
                manual_review_required=False,
                passed=bool(report.get("passed")),
            )
        )


def _initial_state(
    db: Session,
    task: GenerationTask,
    learner: Learner,
    profile: LearnerProfile,
) -> AgentGraphState:
    ability_profile = dict(profile.ability_profile_json or {})
    return {
        "db_session": db,
        "task_id": task.public_id,
        "learner_id": learner.public_id,
        "profile_id": profile.public_id,
        "profile_mode": "load_existing_profile",
        "domain_code": task.domain_code,
        "resource_types": task.resource_types_json or [],
        "learning_goal": "根据诊断结果生成个性化学习资源",
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
    }


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

        task.status = "running"
        task.decision = "pending"
        db.commit()

        state = _initial_state(db, task, learner, profile)
        current_run: AgentRun | None = None

        try:
            step, agent_name, node_func = INITIAL_NODE
            state, current_run, _ = _run_node(
                db,
                task=task,
                state=state,
                step=step,
                agent_name=agent_name,
                node_func=node_func,
            )

            for generation_round in range(1, MAX_GENERATION_ROUNDS + 1):
                state["generation_round"] = generation_round
                for step, agent_name, node_func in LOOP_NODE_SEQUENCE:
                    state, current_run, _ = _run_node(
                        db,
                        task=task,
                        state=state,
                        step=step,
                        agent_name=agent_name,
                        node_func=node_func,
                    )

                if state.get("decision") == "passed":
                    _persist_resources(db, task, profile, state)
                    step, agent_name, node_func = PERSIST_NODE
                    state, current_run, output = _run_node(
                        db,
                        task=task,
                        state=state,
                        step=step,
                        agent_name=agent_name,
                        node_func=node_func,
                    )
                    current_run.output_summary_json = {
                        **(current_run.output_summary_json or {}),
                        "persisted_resources": len(state.get("draft_resources", [])),
                    }
                    db.commit()
                    break

                if state.get("decision") == "failed":
                    break

            task.revision_count = state.get("revision_count", 0)
            task.decision = state.get("decision", "failed")
            task.status = "completed" if task.decision == "passed" else task.decision
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
            if current_run is not None:
                current_run.status = "failed"
                current_run.error_message = str(exc)
                current_run.output_summary_json = {
                    **(current_run.output_summary_json or {}),
                    "error": str(exc),
                }
            task.status = "failed"
            task.decision = "failed"
            _message(
                db,
                task=task,
                sender=(current_run.agent_name if current_run else "generation_worker"),
                message_type="error",
                payload={"task_id": task.public_id, "status": "failed", "error": str(exc)},
            )
            db.commit()
            return {"task_id": task.public_id, "status": "failed", "error": str(exc)}
