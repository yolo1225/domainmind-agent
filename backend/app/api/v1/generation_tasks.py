from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.models import AgentRun, GenerationTask, Learner, LearnerProfile, LearningResource
from app.schemas.common import ApiResponse, ok
from app.services.profile_service import default_profile_for_learner, profile_source, public_id
from app.workers.generation_worker import run_generation_task

router = APIRouter()
RESOURCE_TYPES = {"lecture", "practice_guide", "graded_quiz"}
TRIGGER_TYPES = {"initial_generation", "resource_feedback"}
EXECUTION_MODES = {"auto", "assisted"}
TERMINAL_TASK_STATUSES = {"completed", "failed", "revision_required", "waiting_human"}
ACTIVE_TASK_STATUSES = {"pending", "running", "waiting_human"}
SENSITIVE_KEYS = {"content", "content_md", "draft_resources", "profile", "answers"}

STEP_LABELS = {
    "prepare_task": "任务准备",
    "interpret_feedback": "反馈识别",
    "analyze_profile": "画像分析",
    "retrieve_knowledge": "知识检索",
    "generate_resource": "资源生成",
    "review_resource": "双模型审核",
    "human_review": "人工复核",
    "finalize_task": "确定性收尾",
}


def _get_or_create_learner(db: Session, learner_public_id: str) -> Learner:
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_public_id))
    if learner:
        return learner
    learner = Learner(
        public_id=learner_public_id,
        background="MVP 演示学习者",
        target_domain="ai_app_dev",
        experience_years=0,
        learning_style="mixed",
    )
    db.add(learner)
    db.flush()
    return learner


def _resource_summary(resource: LearningResource) -> dict[str, Any]:
    return {
        "resource_id": resource.public_id,
        "resource_type": resource.resource_type,
        "title": resource.title,
        "difficulty": resource.difficulty,
        "review_status": resource.review_status,
        "version": resource.version,
        "is_current": resource.is_current,
        "sources": [item.get("knowledge_id") for item in (resource.sources_json or [])],
    }


def _profile_summary(db: Session, task: GenerationTask) -> dict[str, Any]:
    profile = db.get(LearnerProfile, task.profile_id)
    if profile is None:
        return {
            "profile_id": None,
            "profile_version": None,
            "profile_source": None,
            "profile_changed_dimensions": [],
        }
    return {
        "profile_id": profile.public_id,
        "profile_version": profile.profile_version,
        "profile_source": profile_source(profile),
        "profile_changed_dimensions": profile.changed_dimensions_json or [],
    }


def _task_detail_summary(db: Session, task: GenerationTask) -> dict[str, Any]:
    learner = db.get(Learner, task.learner_id)
    resources = list(
        db.scalars(
            select(LearningResource)
            .where(LearningResource.generation_task_id == task.id)
            .order_by(LearningResource.id)
        )
    )
    return {
        "task_id": task.public_id,
        "thread_id": task.public_id,
        "status": task.status,
        "progress": task.progress,
        "trigger_type": task.trigger_type,
        "execution_mode": task.execution_mode,
        "learner_id": learner.public_id if learner else None,
        **_profile_summary(db, task),
        "revision_count": task.revision_count,
        "decision": task.decision,
        "resources": [_resource_summary(item) for item in resources],
    }


@router.post("", response_model=ApiResponse)
def create_generation_task(
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> ApiResponse:
    payload = payload or {}
    trigger_type = str(payload.get("trigger_type", "initial_generation"))
    execution_mode = str(payload.get("execution_mode", "auto"))
    if trigger_type not in TRIGGER_TYPES:
        raise HTTPException(status_code=422, detail="unsupported trigger_type")
    if execution_mode not in EXECUTION_MODES:
        raise HTTPException(status_code=422, detail="unsupported execution_mode")
    requested_types = list(payload.get("resource_types") or RESOURCE_TYPES)
    if not requested_types or any(item not in RESOURCE_TYPES for item in requested_types):
        raise HTTPException(status_code=422, detail="unsupported resource type")

    learner = _get_or_create_learner(db, payload.get("learner_id", "learner_001"))
    profile_id = payload.get("profile_id")
    if profile_id:
        profile = db.scalar(
            select(LearnerProfile).where(LearnerProfile.public_id == profile_id)
        )
        if profile is None:
            raise HTTPException(status_code=404, detail="Learner profile not found")
        learner = db.get(Learner, profile.learner_id) or learner
    else:
        profile = default_profile_for_learner(db, learner)
    task = GenerationTask(
        public_id=public_id("task"),
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code=str(payload.get("domain_code", "ai_app_dev")),
        status="pending",
        resource_types_json=requested_types,
        revision_count=0,
        decision="pending",
        trigger_type=trigger_type,
        execution_mode=execution_mode,
        learning_goal=str(payload.get("learning_goal") or "个性化学习资源生成")[:512],
        progress=0,
    )
    db.add(task)
    db.commit()
    background_tasks.add_task(run_generation_task, task.public_id)
    return ok(
        {
            "task_id": task.public_id,
            "thread_id": task.public_id,
            "status": task.status,
            "trigger_type": task.trigger_type,
            "execution_mode": task.execution_mode,
            "resource_types": requested_types,
            "agent_graph": "unified_learning_graph_v1",
            **_profile_summary(db, task),
            "decision": task.decision,
            "agent_trace": [],
            "resources": [],
        }
    )


@router.get("/active", response_model=ApiResponse)
def get_active_generation_task(
    learner_id: str = "learner_001",
    db: Session = Depends(get_db),
) -> ApiResponse:
    task = db.scalar(
        select(GenerationTask)
        .join(Learner, Learner.id == GenerationTask.learner_id)
        .where(Learner.public_id == learner_id)
        .where(GenerationTask.status.in_(ACTIVE_TASK_STATUSES))
        .order_by(GenerationTask.created_at.desc(), GenerationTask.id.desc())
    )
    return ok(_task_detail_summary(db, task) if task is not None else None)


@router.get("/{task_id}", response_model=ApiResponse)
def get_generation_task(task_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
    if task is None:
        raise HTTPException(status_code=404, detail="Generation task not found")
    return ok(_task_detail_summary(db, task))


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items() if key not in SENSITIVE_KEYS}
    if isinstance(value, list):
        return [_safe(item) for item in value[:30]]
    return value


@router.get("/{task_id}/agent-runs", response_model=ApiResponse)
def get_agent_runs(task_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
    if task is None:
        raise HTTPException(status_code=404, detail="Generation task not found")
    runs = list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.generation_task_id == task.id)
            .order_by(AgentRun.id)
        )
    )
    return ok(
        [
            {
                "run_id": run.id,
                "task_id": task.public_id,
                "agent_name": run.agent_name,
                "status": run.status,
                "input_summary": _safe(run.input_summary_json or {}),
                "output_summary": _safe(run.output_summary_json or {}),
                "model_name": run.model_name,
                "prompt_version": run.prompt_version,
                "tokens_input": run.tokens_input,
                "tokens_output": run.tokens_output,
                "duration_ms": run.duration_ms,
                "error": run.error_message,
            }
            for run in runs
        ]
    )


def _json_event(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _agent_payload(task: GenerationTask, run: AgentRun) -> dict[str, Any]:
    output = _safe(run.output_summary_json or {})
    step = str((run.input_summary_json or {}).get("step") or output.get("step") or run.agent_name)
    return {
        "run_id": run.id,
        "task_id": task.public_id,
        "step": step,
        "status": run.status,
        "agent_name": run.agent_name,
        "generation_round": (run.input_summary_json or {}).get("generation_round"),
        "event_message": f"{STEP_LABELS.get(step, step)}{'完成' if run.status == 'completed' else '运行中' if run.status == 'running' else '失败'}",
        "payload": output,
        "timestamp": run.updated_at.isoformat() if run.updated_at else None,
    }


def _serialize_agent_status_event(
    task: GenerationTask, run: AgentRun, step: str
) -> dict[str, Any]:
    """Backward-compatible serializer for existing API/unit consumers."""

    payload = _agent_payload(task, run)
    payload["step"] = step
    generation_round = (run.input_summary_json or {}).get("generation_round") or (
        run.output_summary_json or {}
    ).get("generation_round")
    payload["generation_round"] = generation_round
    payload["is_revision_round"] = bool(generation_round and int(generation_round) > 1)
    if generation_round:
        # Keep the legacy marker in this compatibility-only helper. New SSE
        # consumers use the normal Chinese event message from _agent_payload.
        payload["event_message"] = (
            f"第 {generation_round} 轮（Ек {generation_round} Тж）："
            f"{STEP_LABELS.get(step, step)}完成"
        )
    return payload


def _semantic_events(task: GenerationTask, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if payload["status"] != "completed":
        return []
    step, output = payload["step"], payload["payload"]
    base = {"task_id": task.public_id, **output}
    events: list[tuple[str, dict[str, Any]]] = []
    if step == "prepare_task":
        events.append(("trigger_routed", base))
    elif step == "interpret_feedback":
        events.append(("feedback_classified", base))
    elif step == "analyze_profile":
        events.append(("profile_update_decided", base))
        events.append(("profile_updated" if output.get("profile_update_required") else "profile_unchanged", base))
        if output.get("profile_update_required"):
            events.extend(
                [("path_refresh_started", base), ("path_refresh_completed", base)]
            )
    elif step == "review_resource" and output.get("manual_review_required"):
        events.extend([("review_disagreement", base), ("review_retrieval_started", base)])
    elif step == "human_review":
        name = "manual_review_required" if output.get("decision") == "manual_review_required" else "manual_review_resolved"
        events.append((name, base))
    return events


async def _task_events(task_id: str) -> AsyncIterator[str]:
    emitted: set[tuple[str, int | str, str]] = set()
    while True:
        with SessionLocal() as db:
            task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
            if task is None:
                yield _json_event("task_failed", {"task_id": task_id, "error": "not_found"})
                return
            runs = list(
                db.scalars(
                    select(AgentRun)
                    .where(AgentRun.generation_task_id == task.id)
                    .order_by(AgentRun.id)
                )
            )
            for run in runs:
                key = ("agent_status", run.id, run.status)
                if key in emitted:
                    continue
                emitted.add(key)
                payload = _agent_payload(task, run)
                yield _json_event("agent_status", payload)
                for name, semantic_payload in _semantic_events(task, payload):
                    semantic_key = (name, run.id, run.status)
                    if semantic_key not in emitted:
                        emitted.add(semantic_key)
                        yield _json_event(name, semantic_payload)

            if task.status in TERMINAL_TASK_STATUSES:
                if task.status == "completed":
                    for resource in db.scalars(
                        select(LearningResource).where(
                            LearningResource.generation_task_id == task.id
                        )
                    ):
                        yield _json_event(
                            "resource_created",
                            {"task_id": task.public_id, **_resource_summary(resource)},
                        )
                    name = "task_completed"
                elif task.status == "waiting_human":
                    name = "manual_review_required"
                else:
                    name = "task_failed"
                yield _json_event(
                    name,
                    {
                        "task_id": task.public_id,
                        "step": "task",
                        "status": task.status,
                        "decision": task.decision,
                        "progress": task.progress,
                    },
                )
                return
        await asyncio.sleep(0.35)


@router.get("/{task_id}/events")
async def stream_generation_events(task_id: str) -> StreamingResponse:
    return StreamingResponse(
        _task_events(task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
