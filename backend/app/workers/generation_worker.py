"""V3 generation worker and observability bridge."""

from __future__ import annotations

import time
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.checkpointer import MySQLLangGraphCheckpointer
from app.agents.contracts import (
    CONTRACT_VERSION,
    QUALITY_RULE_VERSION,
    ConversationSummary,
    EvidenceRef,
    EvidenceType,
    FeedbackContext,
    FeedbackIntent,
    FinalizeTaskOutput,
    LearningPathNodeSnapshot,
    LearningPathSnapshot,
    KnowledgeAssessment,
    ResourceSummary,
    TaskRequest,
)
from app.services.domain_runtime_service import load_domain_runtime
from app.agents.graphs import build_learning_graph
from app.agents.observability import collect_model_calls
from app.agents.nodes import GRAPH_STATE, AgentRuntime, build_nodes
from app.agents.prompt_registry import PROMPT_VERSION, node_prompt_hash
from app.agents.review_agent import ReviewBatchCache
from app.core.db import SessionLocal
from app.models import (
    AgentMessageRecord,
    AgentRun,
    AnswerRecord,
    DiagnosticQuestion,
    Feedback,
    GenerationTask,
    GraphCheckpoint,
    KnowledgeUpdateImpact,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
    TutoringMessage,
    TutoringSession,
)
from app.services.generation_service import persist_generated_resources
from app.services.learning_path_service import normalize_learning_path
from app.services.model_config_service import reload_from_db
from app.services.profile_revision_service import persist_profile_revision
from app.services.contract_mapping import profile_snapshot
from app.services.node_generation_target_service import generation_basis_for_task

logger = logging.getLogger(__name__)


NodeFunc = Callable[[GRAPH_STATE], GRAPH_STATE]
NODE_AGENT_NAMES = {
    "prepare_task": "orchestrator_agent",
    "interpret_feedback": "tutoring_agent",
    "analyze_profile": "profile_analysis_agent",
    "retrieve_knowledge": "knowledge_retrieval_agent",
    "generate_resource": "content_generation_agent",
    "review_resource": "review_validation_agent",
    "finalize_task": "orchestrator_agent",
}
NODE_PROGRESS = {
    "prepare_task": 5,
    "interpret_feedback": 15,
    "analyze_profile": 25,
    "retrieve_knowledge": 40,
    "generate_resource": 60,
    "review_resource": 78,
    "finalize_task": 95,
}
RECOVERABLE_CHECKPOINT_FAILURES = {
    "generated_structured_output_invalid",
    "generated_structure_validation_failed",
    # Read-only compatibility for checkpoints created before V6 error typing.
    "invalid_generate_resource_output",
    "generation_execution_failed",
    "review_model_call_failed",
    "review_output_truncated",
    "review_structured_output_invalid",
    "review_execution_failed",
}
INTERRUPTED_TASK_STATUSES = {"running", "retry_pending"}
NODE_ADVANCEMENT_EVENT_TYPE = "node_advancement"
NODE_ADVANCEMENT_RESOURCE_TYPES = {"lecture", "practice_guide", "graded_quiz"}


def _message(
    db: Session,
    task: GenerationTask,
    sender: str,
    payload: dict[str, Any],
    *,
    receiver: str = "orchestrator_agent",
    message_type: str = "observation",
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


def _resource_summary(resource: LearningResource) -> dict[str, Any]:
    return {
        "resource_id": resource.public_id,
        "resource_type": resource.resource_type,
        "title": resource.title,
        "difficulty": resource.difficulty,
        "review_status": resource.review_status,
        "sources": [item.get("knowledge_id") for item in (resource.sources_json or [])],
    }


def _feedback_assessments(
    db: Session,
    task: GenerationTask,
    learner: Learner,
    feedback: Feedback | None,
) -> tuple[list[EvidenceRef], list[KnowledgeAssessment]]:
    if feedback is None:
        return [], []
    # Confirmed mastery behavior is routing evidence for an already-created
    # challenge task. It remains insufficient to change the learner profile.
    evidence: list[EvidenceRef] = []
    retained_types = {EvidenceType.SCORED_QUIZ, EvidenceType.VALIDATED_BEHAVIOR}
    for item in feedback.profile_change_evidence_json or []:
        if not isinstance(item, dict):
            continue
        evidence_type = str(item.get("evidence_type") or item.get("type") or "")
        if evidence_type not in {value.value for value in retained_types}:
            continue
        try:
            restored = EvidenceRef(
                evidence_id=str(item.get("evidence_id") or "")[:64],
                evidence_type=evidence_type,
                summary=str(item.get("summary") or "结构化掌握证据")[:500],
                knowledge_id=(str(item["knowledge_id"])[:64] if item.get("knowledge_id") else None),
                source_ref_id=(str(item["source_ref_id"])[:128] if item.get("source_ref_id") else None),
                confidence=max(0.0, min(1.0, float(item.get("confidence") or 0.0))),
                confirmed=bool(item.get("confirmed", False)),
            )
        except (TypeError, ValueError):
            continue
        if restored.confirmed:
            evidence.append(restored)
    explicit_ids = {
        str(item.get("evidence_id"))
        for item in (feedback.profile_change_evidence_json or [])
        if isinstance(item, dict) and item.get("evidence_id")
    }
    if feedback.tutoring_session_id is None and not explicit_ids:
        return [], []
    assessments: list[KnowledgeAssessment] = []
    for record in db.scalars(select(AnswerRecord).where(AnswerRecord.learner_id == learner.id)):
        summary = record.answer_summary_json or {}
        evidence_id = f"answer_record:{record.id}"
        belongs_to_feedback = (
            summary.get("tutoring_session_id") == feedback.tutoring_session_id
            if feedback.tutoring_session_id is not None
            else evidence_id in explicit_ids
        )
        if not belongs_to_feedback or summary.get("confirmed") is not True or summary.get(
            "consumed_by_profile_id"
        ) is not None:
            continue
        question = db.get(DiagnosticQuestion, record.question_id)
        knowledge = db.get(KnowledgeItem, record.knowledge_item_id)
        if (
            question is None
            or knowledge is None
            or question.domain_code != task.domain_code
            or knowledge.domain_code != task.domain_code
        ):
            continue
        confidence = max(0.0, min(1.0, float(summary.get("confidence") or 0.9)))
        if evidence_id not in {item.evidence_id for item in evidence}:
            evidence.append(
                EvidenceRef(
                    evidence_id=evidence_id,
                    evidence_type=EvidenceType.SCORED_QUIZ,
                    summary="导学正式验证题已由服务端评分",
                    knowledge_id=knowledge.public_id,
                    source_ref_id=question.public_id,
                    confidence=confidence,
                    confirmed=True,
                )
            )
        assessments.append(
            KnowledgeAssessment(
                assessment_id=str(summary.get("assessment_id") or f"assessment_{record.id}"),
                evidence_id=evidence_id,
                knowledge_id=knowledge.public_id,
                score=record.score,
                difficulty=question.difficulty,
                attempted=True,
                confidence=confidence,
            )
        )
    return evidence, assessments


def _initial_state(
    db: Session,
    task: GenerationTask,
    learner: Learner,
    profile: LearnerProfile,
    feedback: Feedback | None,
) -> GRAPH_STATE:
    resource = (
        db.get(LearningResource, task.source_resource_id) if task.source_resource_id else None
    )
    session = (
        db.get(TutoringSession, feedback.tutoring_session_id)
        if feedback is not None and feedback.tutoring_session_id
        else None
    )
    message = (
        db.get(TutoringMessage, feedback.tutoring_message_id)
        if feedback is not None and feedback.tutoring_message_id
        else None
    )
    if task.trigger_type == "resource_feedback" and (feedback is None or resource is None):
        raise ValueError("resource_feedback_task_missing_source_references")
    inherited_targets: dict[str, list[str]] = {
        str(resource_type): list(knowledge_ids or [])
        for resource_type, knowledge_ids in (
            task.resource_knowledge_targets_json or {}
        ).items()
    }
    if not inherited_targets and task.source_task_id:
        source_task = db.get(GenerationTask, task.source_task_id)
        if source_task is None:
            raise ValueError("source_package_not_found")
        if (source_task.package_quality_json or {}).get(
            "quality_rule_version"
        ) != QUALITY_RULE_VERSION:
            raise ValueError("v6_full_regeneration_required")
        stored_targets = (source_task.package_coverage_json or {}).get(
            "resource_knowledge_targets"
        ) or {}
        inherited_targets = {
            resource_type: list(stored_targets.get(resource_type) or [])
            for resource_type in (task.resource_types_json or [])
        }
        if any(not values for values in inherited_targets.values()):
            raise ValueError("v6_source_target_mapping_missing")
    request = TaskRequest(
        task_id=task.public_id,
        session_id=task.public_id,
        trigger_type=task.trigger_type,
        execution_mode=task.execution_mode,
        learner_id=learner.public_id,
        profile_id=profile.public_id,
        domain_code=task.domain_code,
        resource_types=task.resource_types_json or ["lecture"],
        learning_goal=task.learning_goal or "根据诊断结果生成个性化学习资源",
        resource_knowledge_targets=inherited_targets,
        resource_id=resource.public_id if resource else None,
        feedback_id=str(feedback.id) if feedback else None,
        tutoring_session_id=session.public_id if session else None,
        tutoring_message_id=message.public_id if message else None,
    )
    active_profile = profile_snapshot(profile)
    learning_path = db.scalar(
        select(LearningPath)
        .where(
            LearningPath.learner_id == learner.id,
            LearningPath.domain_code == task.domain_code,
            LearningPath.status == "active",
        )
        .order_by(LearningPath.created_at.desc(), LearningPath.id.desc())
    )
    basis = generation_basis_for_task(db, task)
    prerequisites_by_knowledge = {}
    if basis:
        prerequisite_ids = [
            item["knowledge_id"]
            for item in basis.get("prerequisite_knowledge") or []
        ]
        prerequisites_by_knowledge = {
            item["knowledge_id"]: list(prerequisite_ids)
            for item in basis.get("core_knowledge") or []
        }
    path_snapshot, current_path_node = _learning_path_snapshot(
        learning_path,
        active_profile,
        prerequisites_by_knowledge=prerequisites_by_knowledge,
    )
    state: GRAPH_STATE = {
        "contract_version": CONTRACT_VERSION,
        "task_request": request,
        "current_profile": active_profile,
        "revision_plan": None,
    }
    if path_snapshot is not None:
        state["learning_path"] = path_snapshot
    if current_path_node is not None:
        state["current_path_node"] = current_path_node
    if feedback is not None and resource is not None:
        quick_tag = feedback.feedback_intent or feedback.feedback_type
        supporting_evidence, _ = _feedback_assessments(db, task, learner, feedback)
        previous_intents = list(
            db.scalars(
                select(Feedback.feedback_intent)
                .where(
                    Feedback.tutoring_session_id == feedback.tutoring_session_id,
                    Feedback.id != feedback.id,
                    Feedback.feedback_intent.is_not(None),
                )
                .order_by(Feedback.id.desc())
                .limit(20)
            )
        )
        state["feedback_context"] = FeedbackContext(
            resource=ResourceSummary(
                resource_id=resource.public_id,
                resource_type=resource.resource_type,
                title=resource.title,
                difficulty=resource.difficulty,
                source_ref_ids=[
                    item.get("source_ref_id")
                    for item in (resource.sources_json or [])
                    if item.get("source_ref_id")
                ],
            ),
            conversation=ConversationSummary(
                tutoring_session_id=session.public_id if session else task.public_id,
                turn_count=max(1, session.turn_count if session else 1),
                latest_message_summary=(
                    message.content if message else feedback.comment or "学习者提交资源反馈"
                )[:500],
                previous_intents=[
                    item for item in previous_intents if item in {value.value for value in FeedbackIntent}
                ],
            ),
            feedback_summary=(feedback.comment or feedback.feedback_type or "学习者反馈")[:500],
            quick_tag=quick_tag
            if quick_tag in {item.value for item in FeedbackIntent}
            else FeedbackIntent.OTHER,
            rating=feedback.rating,
            supporting_evidence=supporting_evidence,
        )
    return state


def _next_receiver(step: str, patch: GRAPH_STATE) -> str:
    if step == "prepare_task":
        next_node = patch["prepare_task"].next_node
    elif step == "interpret_feedback":
        next_node = "analyze_profile"
    elif step == "analyze_profile":
        next_node = (
            "retrieve_knowledge" if patch["analyze_profile"].needs_generation else "finalize_task"
        )
    elif step == "retrieve_knowledge":
        next_node = "generate_resource"
    elif step == "generate_resource":
        next_node = "review_resource"
    elif step == "review_resource":
        next_node = "finalize_task"
    elif step == "finalize_task":
        decision = patch["finalize_task"].decision.value
        next_node = "retrieve_knowledge" if decision == "revision_required" else "orchestrator_agent"
    else:
        next_node = "orchestrator_agent"
    return NODE_AGENT_NAMES.get(next_node, next_node)


def _learning_path_snapshot(
    path: LearningPath | None,
    profile,
    *,
    prerequisites_by_knowledge: dict[str, list[str]] | None = None,
) -> tuple[LearningPathSnapshot | None, LearningPathNodeSnapshot | None]:
    if path is None:
        return None, None
    payload = normalize_learning_path(path)
    ability_values = list(profile.ability_scores.model_dump().values())
    average_ability = sum(ability_values) / len(ability_values)
    difficulty = max(1, min(5, round(average_ability / 20)))
    nodes: list[LearningPathNodeSnapshot] = []
    for state in (payload.get("node_states") or {}).values():
        if not isinstance(state, dict):
            continue
        knowledge_ids = [str(value) for value in state.get("knowledge_ids") or []]
        nodes.append(
            LearningPathNodeSnapshot(
                path_node_id=str(state["path_node_id"]),
                knowledge_ids=knowledge_ids,
                focus_knowledge_ids=list(state.get("focus_knowledge_ids") or []),
                title=str(state.get("title") or "学习单元"),
                path_order=int(state.get("path_order") or 1),
                target_difficulty=difficulty,
                learning_objective=str(state.get("learning_objective") or "掌握本单元知识"),
                recommendation_reason=str(
                    state.get("recommendation_reason") or "根据画像与知识关系规划。"
                ),
                prerequisite_knowledge_ids=list(state.get("prerequisite_knowledge_ids") or []),
            )
        )
    current_node_id = payload.get("current_node_id")
    current = next((node for node in nodes if node.path_node_id == current_node_id), None)
    return (
        LearningPathSnapshot(
            path_id=path.public_id,
            nodes=nodes,
            current_node_id=current.path_node_id if current else None,
        ),
        current,
    )


def _compact_review_channel(channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_role": channel["model_role"],
        "model_name": channel["model_name"],
        "scores": channel["scores"],
        "passed": channel["passed"],
        "fact_checks": [
            {
                "claim_id": item.get("claim_id"),
                "field_path": item.get("field_path"),
                "verdict": item.get("verdict"),
                "supported": item["supported"],
                "source_ref_ids": item["source_ref_ids"],
                "determinable": item["determinable"],
            }
            for item in channel["fact_checks"]
        ],
        "unable_to_determine": channel["unable_to_determine"],
    }


def _verdict_by_claim(channel: dict[str, Any] | None) -> dict[str, str | None]:
    if not channel:
        return {}
    return {
        str(item.get("claim_id")): item.get("verdict")
        for item in channel.get("fact_checks", [])
        if item.get("claim_id")
    }


def _disputed_claim_ids(
    primary: dict[str, Any] | None, secondary: dict[str, Any] | None
) -> set[str]:
    primary_verdicts = _verdict_by_claim(primary)
    secondary_verdicts = _verdict_by_claim(secondary)
    return {
        claim_id
        for claim_id in primary_verdicts.keys() & secondary_verdicts.keys()
        if primary_verdicts[claim_id] != secondary_verdicts[claim_id]
    }


def _field_type(field_path: str | None) -> str:
    root = (field_path or "unknown").split("[", 1)[0].split(".", 1)[0]
    return root or "unknown"


def _review_observability(report: dict[str, Any]) -> dict[str, Any]:
    primary = report["primary_review"]
    secondary = report["secondary_review"]
    arbitration = report["arbitration"]
    initial_disputed = _disputed_claim_ids(primary, secondary)
    remaining_disputed = _disputed_claim_ids(
        arbitration.get("primary_recheck"), arbitration.get("secondary_recheck")
    )
    field_by_claim = {
        str(item.get("claim_id")): _field_type(item.get("field_path"))
        for item in primary.get("fact_checks", [])
        if item.get("claim_id")
    }
    disputed_field_types: dict[str, int] = {}
    for claim_id in remaining_disputed or initial_disputed:
        field_type = field_by_claim.get(claim_id, "unknown")
        disputed_field_types[field_type] = disputed_field_types.get(field_type, 0) + 1

    tendencies: dict[str, dict[str, int | float]] = {}
    for channel in (primary, secondary):
        checks = channel.get("fact_checks", [])
        supported = sum(item.get("verdict") == "supported" for item in checks)
        tendencies[channel["model_role"]] = {
            "supported": supported,
            "total": len(checks),
            "supported_rate": round(supported / len(checks), 4) if checks else 0.0,
        }
    return {
        "initial_disputed_count": len(initial_disputed),
        "remaining_disputed_count": len(remaining_disputed),
        "disputed_field_types": disputed_field_types,
        "evidence_capability_insufficient_count": sum(
            not item.get("source_ref_ids") for item in primary.get("fact_checks", [])
        ),
        "model_supported_tendency": tendencies,
    }


def _compact_review_report(report: dict[str, Any]) -> dict[str, Any]:
    arbitration = report["arbitration"]
    return {
        "resource_type": report["resource_type"],
        "decision": report["decision"],
        "passed": report["passed"],
        "quality_metrics": report["quality_metrics"],
        "final_scores": report["final_scores"],
        "evidence_ref_ids": report["evidence_ref_ids"],
        "claim_set_hash": report.get("claim_set_hash"),
        "claim_counts": {
            "supported": len(report.get("supported_claim_ids", [])),
            "contradicted": len(report.get("contradicted_claim_ids", [])),
            "evidence_insufficient": len(report.get("undetermined_claim_ids", [])),
            "unable_to_determine": len(report.get("undetermined_claim_ids", [])),
            "unresolved": len(report.get("unresolved_claim_ids", [])),
        },
        "observability": _review_observability(report),
        "primary_review": _compact_review_channel(report["primary_review"]),
        "secondary_review": _compact_review_channel(report["secondary_review"]),
        "arbitration": {
            "required": arbitration["required"],
            "retrieval_performed": arbitration["retrieval_performed"],
            "query_terms": arbitration["query_terms"],
            "additional_source_ref_ids": arbitration["additional_source_ref_ids"],
            "disputed_claim_ids": arbitration.get("disputed_claim_ids", []),
            "disagreement_remains": arbitration["disagreement_remains"],
            "primary_recheck": (
                _compact_review_channel(arbitration["primary_recheck"])
                if arbitration["primary_recheck"]
                else None
            ),
            "secondary_recheck": (
                _compact_review_channel(arbitration["secondary_recheck"])
                if arbitration["secondary_recheck"]
                else None
            ),
        },
    }


def _summary(step: str, patch: GRAPH_STATE) -> dict[str, Any]:
    output = patch.get(step)
    if output is None:
        return {"step": step}
    payload = output.model_dump(mode="json")
    if step == "generate_resource":
        return {
            "step": step,
            "resource_types": [item["resource_type"] for item in payload["resources"]],
        }
    if step == "review_resource":
        reports = [_compact_review_report(item) for item in payload["reports"]]
        return {
            "step": step,
            "decisions": [item["decision"] for item in reports],
            "package_quality": payload["package_quality"],
            "arbitration": [
                {
                    "required": item["arbitration"]["required"],
                    "retrieval_performed": item["arbitration"]["retrieval_performed"],
                    "disagreement_remains": item["arbitration"]["disagreement_remains"],
                    "query_terms": item["arbitration"]["query_terms"],
                    "additional_source_ref_ids": item["arbitration"]["additional_source_ref_ids"],
                }
                for item in reports
            ],
            "resource_reviews": reports,
        }
    if step == "analyze_profile":
        return {
            "step": step,
            "profile_id": payload["profile"]["profile_id"],
            "profile_update_required": payload["profile_update_required"],
            "needs_generation": payload["needs_generation"],
        }
    if step == "finalize_task":
        return {
            "step": step,
            "decision": payload["decision"],
            "revision_count": payload["revision_count"],
        }
    return {"step": step, "task_id": payload.get("task_id")}


def _apply_model_call_metrics(
    run: AgentRun, output: dict[str, Any], model_calls: list[dict[str, Any]]
) -> None:
    if not model_calls:
        return
    modes = {str(item["provider_mode"]) for item in model_calls}
    names = list(dict.fromkeys(str(item["model_name"]) for item in model_calls))
    run.llm_calls = len(model_calls)
    run.tokens_input = sum(int(item["tokens_input"]) for item in model_calls)
    run.tokens_output = sum(int(item["tokens_output"]) for item in model_calls)
    run.tokens_used = run.tokens_input + run.tokens_output
    run.model_name = ",".join(names)[:128]
    output["model_calls"] = model_calls
    output["provider_mode"] = modes.pop() if len(modes) == 1 else "mixed"


def _failure_code(exc: Exception) -> str:
    """Persist controlled error codes without copying arbitrary provider payloads."""
    value = str(exc).strip()
    if value and len(value) <= 128 and value.replace("_", "").isalnum():
        return value
    return type(exc).__name__


def _finalization_failure_code(result: FinalizeTaskOutput | None) -> str:
    """Map a valid final decision to a stable, machine-readable terminal reason."""
    if result is None:
        return "generation_failed"
    if result.decision.value == "failed" and result.revision_count >= 2:
        return "revision_exhausted"
    if result.decision.value == "rejected":
        return "resource_rejected"
    return "generation_incomplete"


def _node_advancement_package_failure(
    db: Session,
    task: GenerationTask,
    result: FinalizeTaskOutput | None,
) -> str | None:
    """Return a terminal failure code for an incomplete confirmed learning package."""
    if task.event_type != NODE_ADVANCEMENT_EVENT_TYPE:
        return None
    expected = set(task.resource_types_json or [])
    if expected != NODE_ADVANCEMENT_RESOURCE_TYPES:
        return "node_package_resource_types_invalid"
    if result is None or result.decision.value == "no_change":
        return "node_package_not_generated"
    resources = list(
        db.scalars(
            select(LearningResource).where(LearningResource.generation_task_id == task.id)
        )
    )
    passed_types = {
        resource.resource_type for resource in resources if resource.review_status == "passed"
    }
    if result.decision.value != "completed" or passed_types != expected:
        return "node_package_resources_incomplete"
    return None


def _restore_refresh_impact(db: Session, task: GenerationTask) -> None:
    if task.event_type != "knowledge_refresh" or not task.source_task_id:
        return
    impact = db.scalar(
        select(KnowledgeUpdateImpact)
        .where(
            KnowledgeUpdateImpact.package_task_id == task.source_task_id,
            KnowledgeUpdateImpact.resolved_by_task_id == task.id,
            KnowledgeUpdateImpact.status == "refreshing",
        )
        .order_by(KnowledgeUpdateImpact.id.desc())
    )
    if impact is not None:
        impact.status = "pending"
        impact.resolved_by_task_id = None


def _persist_profile_update(
    db: Session, task: GenerationTask, original: LearnerProfile, state: GRAPH_STATE
) -> LearnerProfile:
    analysis = state.get("analyze_profile")
    if analysis is None:
        return original
    next_profile, next_path = persist_profile_revision(
        db,
        original=original,
        analysis=analysis,
        trigger_feedback_id=task.source_feedback_id,
    )
    if next_profile.id == original.id:
        return original
    task.profile_id = next_profile.id
    if next_path is not None:
        task.learning_path_id = next_path.id
        task.path_node_id = (next_path.path_json or {}).get("current_node_id")
    return next_profile


def _persist_finalization_revision_count(task: GenerationTask, patch: GRAPH_STATE) -> None:
    finalized = patch.get("finalize_task")
    if finalized is not None:
        task.revision_count = max(task.revision_count, int(finalized.revision_count))


def _observable_node(
    db: Session,
    task: GenerationTask,
    profile: LearnerProfile,
    step: str,
    node: NodeFunc,
    runtime: AgentRuntime,
) -> NodeFunc:
    agent_name = NODE_AGENT_NAMES[step]

    def wrapped(state: GRAPH_STATE) -> GRAPH_STATE:
        started = time.perf_counter()
        initial_output: dict[str, Any] = {"step": step}
        if step == "review_resource":
            initial_output["review_batch_cache"] = runtime.review_batch_cache.snapshot()
        run = AgentRun(
            generation_task_id=task.id,
            agent_name=agent_name,
            status="running",
            input_summary_json={
                "task_id": task.public_id,
                "thread_id": task.public_id,
                "step": step,
                "contract_version": CONTRACT_VERSION,
            },
            output_summary_json=initial_output,
            prompt_version=PROMPT_VERSION,
            prompt_hash=node_prompt_hash(step),
            contract_version=CONTRACT_VERSION,
        )
        db.add(run)
        _message(
            db,
            task,
            "orchestrator_agent",
            {"step": step, "status": "running", "contract_version": CONTRACT_VERSION},
            receiver=agent_name,
        )
        db.commit()
        if step == "review_resource":

            def persist_review_cache(snapshot: dict[str, Any]) -> None:
                current = dict(run.output_summary_json or {})
                current["review_batch_cache"] = snapshot
                run.output_summary_json = current
                db.add(run)
                db.commit()

            runtime.review_batch_cache.set_persist_callback(persist_review_cache)
        model_calls: list[dict[str, Any]] = []
        try:
            path_refresh: dict[str, str | None] | None = None
            with collect_model_calls() as collector:
                patch = node(state)
            model_calls = collector.snapshot()
            next_state = {**state, **patch}
            if step == "analyze_profile":
                updated_profile = _persist_profile_update(db, task, profile, next_state)
                if updated_profile.id != profile.id:
                    new_path = db.scalar(
                        select(LearningPath)
                        .where(LearningPath.profile_id == updated_profile.id)
                        .order_by(LearningPath.id.desc())
                    )
                    old_path = db.scalar(
                        select(LearningPath)
                        .where(LearningPath.profile_id == profile.id)
                        .order_by(LearningPath.id.desc())
                    )
                    path_refresh = {
                        "old_path_id": old_path.public_id if old_path else None,
                        "new_path_id": new_path.public_id if new_path else None,
                    }
                if updated_profile.id == profile.id and task.source_feedback_id:
                    feedback = db.get(Feedback, task.source_feedback_id)
                    if feedback is not None:
                        feedback.profile_update_required = False
                        feedback.decision_reason = patch["analyze_profile"].decision_reason
            if step == "finalize_task":
                _persist_finalization_revision_count(task, patch)
                persist_generated_resources(
                    db, task, db.get(LearnerProfile, task.profile_id) or profile, next_state
                )
            output = _summary(step, patch)
            if path_refresh is not None:
                output["path_refresh"] = path_refresh
            if step == "review_resource":
                output["review_batch_cache"] = runtime.review_batch_cache.snapshot()
            _apply_model_call_metrics(run, output, model_calls)
            run.status = "completed"
            run.output_summary_json = output
            run.duration_ms = round((time.perf_counter() - started) * 1000)
            task.progress = max(task.progress, NODE_PROGRESS[step])
            _message(
                db,
                task,
                agent_name,
                {
                    "step": step,
                    "status": "completed",
                    "output": output,
                    "contract_version": CONTRACT_VERSION,
                },
                receiver=_next_receiver(step, patch),
                message_type="result",
            )
            db.commit()
            return patch
        except Exception as exc:
            if "collector" in locals():
                model_calls = collector.snapshot()
            run.status = "failed"
            run.error_message = str(exc)
            output = {
                "step": step,
                "error": type(exc).__name__,
                "failure_code": _failure_code(exc),
                "failed_step": step,
                "recoverable": step
                in {
                    "retrieve_knowledge",
                    "generate_resource",
                    "review_resource",
                },
                "resource_types": list(
                    dict.fromkeys(
                        str(item.get("resource_type"))
                        for item in model_calls
                        if item.get("resource_type")
                    )
                ),
                "model_roles": list(
                    dict.fromkeys(str(item.get("role")) for item in model_calls if item.get("role"))
                ),
            }
            field_paths = getattr(exc, "field_paths", None)
            if isinstance(field_paths, list) and field_paths:
                output["field_paths"] = [str(path)[:200] for path in field_paths[:20]]
            violations = getattr(exc, "violations", None)
            if isinstance(violations, list) and violations:
                output["policy_violations"] = violations[:20]
            if step == "review_resource":
                output["review_batch_cache"] = runtime.review_batch_cache.snapshot()
            _apply_model_call_metrics(run, output, model_calls)
            run.output_summary_json = output
            run.duration_ms = round((time.perf_counter() - started) * 1000)
            error_payload = {
                "step": step,
                "status": "failed",
                "error": type(exc).__name__,
                "failure_code": _failure_code(exc),
            }
            if output.get("field_paths"):
                error_payload["field_paths"] = output["field_paths"]
            _message(
                db,
                task,
                agent_name,
                error_payload,
                message_type="error",
            )
            db.commit()
            raise
        finally:
            if step == "review_resource":
                runtime.review_batch_cache.set_persist_callback(None)

    return wrapped


def _build_graph(
    db: Session,
    task: GenerationTask,
    profile: LearnerProfile,
    checkpointer: MySQLLangGraphCheckpointer,
    runtime: AgentRuntime,
):
    return build_learning_graph(
        {
            step: _observable_node(db, task, profile, step, node, runtime)
            for step, node in build_nodes(runtime).items()
        },
        checkpointer=checkpointer,
        runtime=runtime,
    )


def _load_review_batch_cache(db: Session, task: GenerationTask) -> ReviewBatchCache:
    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.generation_task_id == task.id)
        .where(AgentRun.agent_name == "review_validation_agent")
        .order_by(AgentRun.id.desc())
    )
    for run in runs:
        output = run.output_summary_json or {}
        snapshot = output.get("review_batch_cache")
        if isinstance(snapshot, dict) and snapshot.get("entries"):
            return ReviewBatchCache(snapshot)
    return ReviewBatchCache()


def recover_interrupted_generation_tasks() -> list[str]:
    """Claim interrupted tasks for one checkpoint-backed startup recovery."""

    claimed: list[str] = []
    with SessionLocal() as db:
        tasks = list(
            db.scalars(
                select(GenerationTask)
                .where(GenerationTask.status.in_(INTERRUPTED_TASK_STATUSES))
                .order_by(GenerationTask.id)
            )
        )
        for task in tasks:
            checkpoint = db.scalar(
                select(GraphCheckpoint).where(GraphCheckpoint.task_id == task.public_id)
            )
            checkpoint_payload = dict(checkpoint.state_json or {}) if checkpoint else {}
            recovery_count = int(checkpoint_payload.get("auto_recovery_count") or 0)
            has_native_checkpoint = bool(checkpoint_payload.get("native_checkpoint"))
            latest_run = db.scalar(
                select(AgentRun)
                .where(AgentRun.generation_task_id == task.id)
                .order_by(AgentRun.id.desc())
            )
            checkpoint_contract_version = str(
                checkpoint_payload.get("contract_version")
                or (latest_run.contract_version if latest_run is not None else "")
                or ""
            )
            stale_contract_checkpoint = bool(
                has_native_checkpoint
                and checkpoint_contract_version != CONTRACT_VERSION
            )
            running_runs = list(
                db.scalars(
                    select(AgentRun)
                    .where(AgentRun.generation_task_id == task.id)
                    .where(AgentRun.status == "running")
                    .order_by(AgentRun.id)
                )
            )
            failure_code = (
                "checkpoint_recovery_exhausted"
                if has_native_checkpoint and recovery_count >= 1
                else "checkpoint_missing_after_interruption"
            )
            for run in running_runs:
                output = dict(run.output_summary_json or {})
                output.update(
                    {
                        "error": "ProcessInterrupted",
                        "failure_code": "persistence_interrupted",
                        "failed_step": (run.input_summary_json or {}).get("step"),
                        "recoverable": stale_contract_checkpoint
                        or (has_native_checkpoint and recovery_count < 1),
                    }
                )
                run.status = "failed"
                run.error_message = "persistence_interrupted"
                run.output_summary_json = output

            if stale_contract_checkpoint:
                db.delete(checkpoint)
                task.status = "retry_pending"
                task.decision = "pending"
                task.progress = 0
                task.failure_reason = ""
                claimed.append(task.public_id)
                _message(
                    db,
                    task,
                    "generation_worker",
                    {
                        "task_id": task.public_id,
                        "status": "checkpoint_contract_refresh",
                        "previous_contract_version": checkpoint_contract_version,
                        "contract_version": CONTRACT_VERSION,
                    },
                    message_type="event",
                )
            elif has_native_checkpoint and recovery_count < 1:
                checkpoint_payload["auto_recovery_count"] = recovery_count + 1
                checkpoint.state_json = checkpoint_payload
                checkpoint.status = "recovery_scheduled"
                task.status = "retry_pending"
                task.decision = "pending"
                task.failure_reason = ""
                claimed.append(task.public_id)
                _message(
                    db,
                    task,
                    "generation_worker",
                    {
                        "task_id": task.public_id,
                        "status": "checkpoint_auto_recovery",
                        "failure_code": "persistence_interrupted",
                        "retry_count": recovery_count + 1,
                    },
                    message_type="event",
                )
            else:
                task.status = "failed"
                task.decision = "failed"
                task.failure_reason = failure_code
                _restore_refresh_impact(db, task)
                _message(
                    db,
                    task,
                    "generation_worker",
                    {
                        "task_id": task.public_id,
                        "status": "failed",
                        "failure_code": failure_code,
                        "failed_step": "generation_worker",
                    },
                    message_type="error",
                )
        db.commit()
    return claimed


def run_generation_task(task_id: str) -> dict[str, Any]:
    # Model settings are persisted in MySQL and may be changed after backend startup.
    # Reload them before constructing retrieval and generation agents.
    reload_from_db()
    with SessionLocal() as db:
        task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
        if task is None:
            return {"task_id": task_id, "status": "not_found"}
        if task.status == "completed" and task.decision in {"completed", "no_change"}:
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
                "resources": [_resource_summary(item) for item in resources],
            }
        learner, profile = db.get(Learner, task.learner_id), db.get(LearnerProfile, task.profile_id)
        if learner is None or profile is None:
            task.status = task.decision = "failed"
            db.commit()
            return {"task_id": task_id, "status": "failed"}
        feedback = db.get(Feedback, task.source_feedback_id) if task.source_feedback_id else None
        resume_failed = task.status in {"failed", "retry_pending"}
        task.status = "running"
        task.decision = "pending"
        db.commit()
        review_batch_cache = _load_review_batch_cache(db, task)
        domain_runtime = load_domain_runtime(db, task.domain_code)
        if not domain_runtime.generation_ready or domain_runtime.profile_config is None:
            raise ValueError(f"DOMAIN_GENERATION_NOT_READY:{','.join(domain_runtime.reasons)}")
        runtime = AgentRuntime.production(
            profile_config=domain_runtime.profile_config,
            domain_code=task.domain_code,
            domain_display_name=domain_runtime.display_name,
            review_batch_cache=review_batch_cache,
            evidence_capabilities_by_knowledge={
                item.public_id: list(item.evidence_capabilities_json or [])
                for item in db.scalars(
                    select(KnowledgeItem).where(
                        KnowledgeItem.domain_code == task.domain_code,
                        KnowledgeItem.status == "published",
                    )
                )
            },
        )
        _, runtime.knowledge_assessments = _feedback_assessments(db, task, learner, feedback)
        checkpointer = MySQLLangGraphCheckpointer(SessionLocal)
        try:
            graph = _build_graph(db, task, profile, checkpointer, runtime)
            graph_config = {"configurable": {"thread_id": task.public_id}}
            graph_input: GRAPH_STATE | None = _initial_state(db, task, learner, profile, feedback)
            if resume_failed and checkpointer.get_tuple(graph_config) is not None:
                # A failed LangGraph node leaves the last successful checkpoint
                # intact. Invoking with None resumes that node and preserves the
                # generated resources already present in state.
                graph_input = None
            final = None
            for checkpoint_attempt in range(2):
                try:
                    final = graph.invoke(graph_input, config=graph_config)
                    break
                except Exception as exc:
                    failure_code = _failure_code(exc)
                    can_resume = (
                        checkpoint_attempt == 0
                        and failure_code in RECOVERABLE_CHECKPOINT_FAILURES
                        and checkpointer.get_tuple(graph_config) is not None
                    )
                    if not can_resume:
                        raise
                    _message(
                        db,
                        task,
                        "generation_worker",
                        {
                            "task_id": task.public_id,
                            "status": "checkpoint_retry",
                            "failure_code": failure_code,
                            "retry_count": 1,
                        },
                        message_type="event",
                    )
                    db.commit()
                    graph_input = None
            if final is None:  # pragma: no cover - loop either returns or raises
                raise RuntimeError("checkpoint_resume_failed")
            result = final.get("finalize_task")
            task.revision_count = result.revision_count if result else 0
            task.decision = result.decision.value if result else "failed"
            node_package_failure = _node_advancement_package_failure(db, task, result)
            if node_package_failure:
                task.status = "failed"
                task.decision = "failed"
                task.failure_reason = node_package_failure
                _restore_refresh_impact(db, task)
                _message(
                    db,
                    task,
                    "generation_worker",
                    {
                        "task_id": task.public_id,
                        "status": "failed",
                        "failure_code": node_package_failure,
                        "failed_step": "finalize_task",
                    },
                    message_type="error",
                )
            elif task.decision in {"completed", "no_change"}:
                task.status = "completed"
                task.progress = 100
                task.failure_reason = ""
                checkpointer.mark_status(task.public_id, "resolved")
            else:
                task.status = "failed"
                task.failure_reason = _finalization_failure_code(result)
                _restore_refresh_impact(db, task)
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
                "resources": [_resource_summary(item) for item in resources],
            }
        except Exception as exc:
            logger.exception(
                "generation task failed before finalization task_id=%s error_type=%s",
                task.public_id,
                type(exc).__name__,
            )
            task.status = task.decision = "failed"
            task.failure_reason = _failure_code(exc)
            _restore_refresh_impact(db, task)
            _message(
                db,
                task,
                "generation_worker",
                {
                    "task_id": task.public_id,
                    "status": "failed",
                    "error": type(exc).__name__,
                    "failure_code": _failure_code(exc),
                    "failed_step": "generation_worker",
                },
                message_type="error",
            )
            db.commit()
            return {"task_id": task.public_id, "status": "failed", "error": type(exc).__name__}
        finally:
            runtime.close()
