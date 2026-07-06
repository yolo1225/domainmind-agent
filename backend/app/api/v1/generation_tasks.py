import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import AgentRun, GenerationTask
from app.schemas.common import ApiResponse, ok
from app.services.demo_flow_service import create_generation_task as run_generation_task

router = APIRouter()


@router.post("", response_model=ApiResponse)
def create_generation_task(
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> ApiResponse:
    payload = payload or {}
    return ok(
        run_generation_task(
            db,
            learner_id=payload.get("learner_id", "learner_001"),
            profile_id=payload.get("profile_id"),
            domain_code=payload.get("domain_code", "ai_app_dev"),
            resource_types=payload.get("resource_types"),
        )
    )


@router.get("/{task_id}", response_model=ApiResponse)
def get_generation_task(task_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
    if task is None:
        raise HTTPException(status_code=404, detail=f"Generation task not found: {task_id}")
    return ok(
        {
            "task_id": task_id,
            "status": task.status,
            "revision_count": task.revision_count,
            "decision": task.decision,
        }
    )


async def _demo_events(task_id: str, steps: list[tuple[str, str]]) -> AsyncIterator[str]:
    for step, status in steps:
        payload = {"task_id": task_id, "step": step, "status": status}
        yield f"event: agent_status\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.2)


@router.get("/{task_id}/events")
async def stream_generation_events(
    task_id: str,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
    steps = [
        ("load_profile", "completed"),
        ("retrieve_knowledge", "completed"),
        ("generate_resource", "completed"),
        ("review_resource", "completed"),
        ("decide_next_step", "completed"),
    ]
    if task is not None:
        runs = list(
            db.scalars(
                select(AgentRun)
                .where(AgentRun.generation_task_id == task.id)
                .order_by(AgentRun.id)
            )
        )
        if runs:
            steps = [(run.agent_name, run.status) for run in runs]
    return StreamingResponse(_demo_events(task_id, steps), media_type="text/event-stream")
