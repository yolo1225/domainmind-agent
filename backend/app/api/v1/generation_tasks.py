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
SENSITIVE_PAYLOAD_KEYS = {
    "answers",
    "answer_text",
    "content",
    "content_md",
    "draft_resources",
    "profile",
    "profile_result",
}

STEP_LABELS = {
    "load_profile": "加载学习画像",
    "retrieve_knowledge": "检索领域知识",
    "generate_resource": "生成学习资源",
    "review_resource": "审核与校验",
    "decide_next_step": "协同决策",
    "persist_resource": "资源入库",
    "task": "任务状态",
}

RESOURCE_TYPE_LABELS = {
    "lecture": "讲义",
    "practice_guide": "实训指导",
    "graded_quiz": "分级测验",
}


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


def _safe_event_payload(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            if key in SENSITIVE_PAYLOAD_KEYS:
                continue
            safe[key] = _safe_event_payload(item)
        return safe
    if isinstance(value, list):
        return [_safe_event_payload(item) for item in value[:20]]
    return value


def _resource_type_text(resource_types: list[Any]) -> str:
    labels = [RESOURCE_TYPE_LABELS.get(str(item), str(item)) for item in resource_types]
    return "、".join(labels)


def _agent_event_message(step: str, status: str, payload: dict[str, Any], generation_round: int | None) -> str:
    round_prefix = f"第 {generation_round} 轮：" if generation_round else ""
    if status == "running":
        return f"{round_prefix}{STEP_LABELS.get(step, step)}开始运行"
    if status == "failed":
        return f"{round_prefix}{STEP_LABELS.get(step, step)}执行失败"

    if step == "load_profile":
        return (
            f"画像类型 {payload.get('profile_type', 'unknown')}，"
            f"策略 {payload.get('strategy', 'unknown')}，"
            f"目标难度 {payload.get('target_difficulty', '-')}"
        )
    if step == "retrieve_knowledge":
        retrieved = payload.get("retrieved") or []
        return (
            f"{round_prefix}召回 {len(retrieved)} 个来源，"
            f"priority {payload.get('matched_priority_count', 0)}，"
            f"prerequisite {payload.get('matched_prerequisite_count', 0)}"
        )
    if step == "generate_resource":
        generated = payload.get("generated_resource_count", payload.get("resource_count", 0))
        preserved = payload.get("preserved_resource_count", 0)
        return f"{round_prefix}生成 {generated} 类资源，保留已通过资源 {preserved} 个"
    if step == "review_resource":
        return (
            f"{round_prefix}平均审核分 {payload.get('average_score', 0)}，"
            f"需修订 {payload.get('revision_required_count', 0)}，"
            f"失败 {payload.get('failed_count', 0)}"
        )
    if step == "decide_next_step":
        decision = payload.get("decision", "pending")
        revision_types = payload.get("revision_resource_types") or []
        if decision == "revision_required":
            return f"{round_prefix}审核要求修订 {_resource_type_text(revision_types)}"
        if decision == "passed":
            return f"{round_prefix}全部资源通过审核"
        if decision == "failed":
            return f"{round_prefix}资源生成未通过审核"
        return f"{round_prefix}决策结果 {decision}"
    if step == "persist_resource":
        return f"{round_prefix}已入库 {payload.get('persisted_resources', payload.get('resource_count', 0))} 个资源"
    return f"{round_prefix}{STEP_LABELS.get(step, step)}已更新"


def _serialize_agent_status_event(task: GenerationTask, run: AgentRun, step: str) -> dict[str, Any]:
    input_summary = run.input_summary_json or {}
    output_summary = run.output_summary_json or {}
    payload = _safe_event_payload(output_summary)
    generation_round = input_summary.get("generation_round") or output_summary.get("generation_round")
    if generation_round is not None:
        generation_round = int(generation_round)
    return {
        "run_id": run.id,
        "task_id": task.public_id,
        "step": step,
        "status": run.status,
        "agent_name": run.agent_name,
        "generation_round": generation_round,
        "is_revision_round": bool(generation_round and generation_round > 1),
        "event_message": _agent_event_message(step, run.status, payload, generation_round),
        "payload": payload,
        "timestamp": run.updated_at.isoformat() if run.updated_at else None,
    }


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
                yield _json_event("agent_status", _serialize_agent_status_event(task, run, step))

            if task.status in TERMINAL_TASK_STATUSES:
                yield _json_event(
                    "task_status",
                    {
                        "task_id": task.public_id,
                        "step": "task",
                        "status": task.status,
                        "decision": task.decision,
                        "event_message": f"任务结束：{task.decision}",
                    },
                )
                return

        await asyncio.sleep(0.35)


@router.get("/{task_id}/events")
async def stream_generation_events(task_id: str) -> StreamingResponse:
    return StreamingResponse(_task_events(task_id), media_type="text/event-stream")
