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
from app.services.profile_service import default_profile_for_learner, public_id
from app.workers.generation_worker import run_generation_task

router = APIRouter()

RESOURCE_TYPES = ["lecture", "practice_guide", "graded_quiz"]
TERMINAL_TASK_STATUSES = {"completed", "failed", "revision_required"}


def _get_or_create_learner(db: Session, learner_public_id: str) -> Learner:
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_public_id))
    if learner is not None:
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


def _serialize_resource_summary(resource: LearningResource) -> dict[str, Any]:
    return {
        "resource_id": resource.public_id,
        "resource_type": resource.resource_type,
        "title": resource.title,
        "difficulty": resource.difficulty,
        "review_status": resource.review_status,
        "sources": [item.get("knowledge_id") for item in (resource.sources_json or [])],
    }


@router.post("", response_model=ApiResponse)
def create_generation_task(
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> ApiResponse:
    payload = payload or {}
    learner = _get_or_create_learner(db, payload.get("learner_id", "learner_001"))
    profile_id = payload.get("profile_id")
    if profile_id:
        profile = db.scalar(select(LearnerProfile).where(LearnerProfile.public_id == profile_id))
        if profile is None:
            raise HTTPException(status_code=404, detail=f"Learner profile not found: {profile_id}")
        profile_learner = db.get(Learner, profile.learner_id)
        if profile_learner is None:
            raise HTTPException(status_code=404, detail=f"Learner not found for profile: {profile_id}")
        learner = profile_learner
    else:
        profile = default_profile_for_learner(db, learner)

    requested_types = payload.get("resource_types") or RESOURCE_TYPES
    task = GenerationTask(
        public_id=public_id("task"),
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code=payload.get("domain_code", "ai_app_dev"),
        status="pending",
        resource_types_json=requested_types,
        revision_count=0,
        decision="pending",
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    background_tasks.add_task(run_generation_task, task.public_id)
    return ok(
        {
            "task_id": task.public_id,
            "status": task.status,
            "resource_types": requested_types,
            "agent_graph": "stategraph_mvp_async",
            "decision": task.decision,
            "agent_trace": [],
            "resources": [],
        }
    )


@router.get("/{task_id}", response_model=ApiResponse)
def get_generation_task(task_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
    if task is None:
        raise HTTPException(status_code=404, detail=f"Generation task not found: {task_id}")
    resources = list(
        db.scalars(
            select(LearningResource)
            .where(LearningResource.generation_task_id == task.id)
            .order_by(LearningResource.id)
        )
    )
    return ok(
        {
            "task_id": task_id,
            "status": task.status,
            "revision_count": task.revision_count,
            "decision": task.decision,
            "resources": [_serialize_resource_summary(resource) for resource in resources],
        }
    )


def _json_event(event_name: str, payload: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _task_events(task_id: str) -> AsyncIterator[str]:
    emitted_run_statuses: set[tuple[int, str]] = set()
    while True:
        with SessionLocal() as db:
            task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
            if task is None:
                yield _json_event(
                    "task_status",
                    {"task_id": task_id, "step": "task", "status": "failed", "message": "not_found"},
                )
                return

            runs = list(
                db.scalars(
                    select(AgentRun)
                    .where(AgentRun.generation_task_id == task.id)
                    .order_by(AgentRun.id)
                )
            )
            for run in runs:
                status_key = (run.id, run.status)
                if status_key in emitted_run_statuses:
                    continue
                emitted_run_statuses.add(status_key)
                step = (run.input_summary_json or {}).get("step") or (
                    run.output_summary_json or {}
                ).get("step") or run.agent_name
                yield _json_event(
                    "agent_status",
                    {
                        "task_id": task.public_id,
                        "step": step,
                        "status": run.status,
                        "agent_name": run.agent_name,
                        "payload": run.output_summary_json or {},
                        "timestamp": run.updated_at.isoformat() if run.updated_at else None,
                    },
                )

            if task.status in TERMINAL_TASK_STATUSES:
                yield _json_event(
                    "task_status",
                    {
                        "task_id": task.public_id,
                        "step": "task",
                        "status": task.status,
                        "decision": task.decision,
                    },
                )
                return

        await asyncio.sleep(0.35)


@router.get("/{task_id}/events")
async def stream_generation_events(task_id: str) -> StreamingResponse:
    return StreamingResponse(_task_events(task_id), media_type="text/event-stream")
