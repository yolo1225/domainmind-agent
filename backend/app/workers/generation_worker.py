from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.nodes import (
    decide_next_step,
    generate_resource,
    load_profile,
    persist_resource,
    retrieve_knowledge,
    review_resource,
    route_after_decision,
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
)
from app.services.generation_service import persist_generated_resources

NodeFunc = Callable[[AgentGraphState], AgentGraphState]

NODE_AGENT_NAMES = {
    "load_profile": "profile_analysis_agent",
    "retrieve_knowledge": "knowledge_retrieval_agent",
    "generate_resource": "content_generation_agent",
    "review_resource": "review_validation_agent",
    "decide_next_step": "orchestrator_agent",
    "persist_resource": "orchestrator_agent",
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
        try:
            if step == "retrieve_knowledge":
                state["generation_round"] = int(state.get("generation_round") or 0) + 1
            if step == "persist_resource":
                persist_generated_resources(db, task, profile, state)
                db.flush()

            next_state = node_func(state)
            output = _latest_trace_output(next_state, previous_trace_count)
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
            return next_state
        except Exception as exc:
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
):
    graph = StateGraph(AgentGraphState)
    graph.add_node(
        "load_profile",
        _observable_node(
            db=db,
            task=task,
            profile=profile,
            step="load_profile",
            node_func=load_profile,
        ),
    )
    graph.add_node(
        "retrieve_knowledge",
        _observable_node(
            db=db,
            task=task,
            profile=profile,
            step="retrieve_knowledge",
            node_func=retrieve_knowledge,
        ),
    )
    graph.add_node(
        "generate_resource",
        _observable_node(
            db=db,
            task=task,
            profile=profile,
            step="generate_resource",
            node_func=generate_resource,
        ),
    )
    graph.add_node(
        "review_resource",
        _observable_node(
            db=db,
            task=task,
            profile=profile,
            step="review_resource",
            node_func=review_resource,
        ),
    )
    graph.add_node(
        "decide_next_step",
        _observable_node(
            db=db,
            task=task,
            profile=profile,
            step="decide_next_step",
            node_func=decide_next_step,
        ),
    )
    graph.add_node(
        "persist_resource",
        _observable_node(
            db=db,
            task=task,
            profile=profile,
            step="persist_resource",
            node_func=persist_resource,
        ),
    )

    graph.add_edge(START, "load_profile")
    graph.add_edge("load_profile", "retrieve_knowledge")
    graph.add_edge("retrieve_knowledge", "generate_resource")
    graph.add_edge("generate_resource", "review_resource")
    graph.add_edge("review_resource", "decide_next_step")
    graph.add_conditional_edges(
        "decide_next_step",
        route_after_decision,
        {
            "persist_resource": "persist_resource",
            "retrieve_knowledge": "retrieve_knowledge",
            "end": END,
        },
    )
    graph.add_edge("persist_resource", END)
    return graph.compile()


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

        try:
            graph = _build_observable_generation_graph(db, task, profile)
            final_state = graph.invoke(
                state,
                config={"configurable": {"thread_id": task.public_id}},
            )

            task.revision_count = final_state.get("revision_count", 0)
            task.decision = final_state.get("decision", "failed")
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
