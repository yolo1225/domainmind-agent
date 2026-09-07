from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.contracts import (
    AnalyzeProfileInput,
    EvidenceRef,
    EvidenceType,
    KnowledgeAssessment,
    LearningPathNodeSnapshot,
    LearningPathSnapshot,
    RecommendedAction,
    TaskContext,
)
from app.agents.observability import collect_model_calls
from app.agents.profile_analysis_agent import ProfileAnalysisAgent
from app.agents.prompt_registry import PROMPT_VERSION, prompt_hash
from app.core.compatibility import AGENT_CONTRACT_VERSION
from app.models import (
    AgentMessageRecord,
    AgentRun,
    AnswerRecord,
    DiagnosticQuestion,
    Feedback,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearnerProfile,
    LearningAdjustmentProposal,
    LearningPath,
    LearningResource,
    PathNodeAssessment,
    TutoringMessage,
    TutoringSession,
)
from app.services.contract_mapping import profile_snapshot
from app.services.domain_runtime_service import load_domain_runtime
from app.services.feedback_service import create_feedback_task
from app.services.learning_path_service import (
    _advance_path_node,
    normalize_learning_path,
    reprioritize_future_nodes,
)
from app.services.profile_revision_service import persist_profile_revision
from app.services.profile_knowledge_state_service import (
    STATE_KEY,
    build_knowledge_state,
    project_analysis_with_knowledge_state,
)
from app.services.node_generation_target_service import (
    bind_node_generation_targets,
    resolve_node_generation_basis,
)
from app.services.node_mastery_service import (
    build_node_gate,
)
from app.services.resource_matching_service import decide_resource_matching
from app.services.learning_package_service import package_member_rows
from app.services.profile_service import public_id
from app.services.question_bank_service import (
    QuestionBankError,
    graded_quiz_preflight,
    select_mastery_question,
)


OPEN_PROPOSAL_STATUSES = {"collecting", "pending_validation"}
INTENT_HYPOTHESES = {"too_easy": "mastery_up", "too_hard": "support_down"}
NODE_ADVANCEMENT_EVENT_TYPE = "node_advancement"
NODE_ADVANCEMENT_RESOURCE_TYPES = {"lecture", "practice_guide", "graded_quiz"}


def _active_context(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
    resource: LearningResource,
) -> tuple[Learner, LearningPath, GenerationTask, dict[str, Any]]:
    learner = db.get(Learner, session.learner_id)
    task = db.get(GenerationTask, resource.generation_task_id)
    path = db.scalar(
        select(LearningPath)
        .where(
            LearningPath.learner_id == session.learner_id,
            LearningPath.domain_code == profile.domain_code,
            LearningPath.status == "active",
        )
        .order_by(LearningPath.created_at.desc(), LearningPath.id.desc())
    )
    if learner is None or task is None or path is None:
        raise ValueError("learning_adjustment_context_missing")
    payload = normalize_learning_path(path)
    node_id = payload.get("current_node_id")
    node = (payload.get("node_states") or {}).get(node_id) if node_id else None
    if (
        not isinstance(node, dict)
        or task.learning_path_id != path.id
        or task.path_node_id != node_id
        or profile.id != path.profile_id
    ):
        raise ValueError("learning_adjustment_context_stale")
    return learner, path, task, node


def _pending_proposal(
    db: Session, *, learner_id: int, path_id: int, node_id: str
) -> LearningAdjustmentProposal | None:
    return db.scalar(
        select(LearningAdjustmentProposal)
        .where(
            LearningAdjustmentProposal.learner_id == learner_id,
            LearningAdjustmentProposal.learning_path_id == path_id,
            LearningAdjustmentProposal.path_node_id == node_id,
            LearningAdjustmentProposal.status.in_(OPEN_PROPOSAL_STATUSES),
        )
        .order_by(LearningAdjustmentProposal.id.desc())
    )


def _qualifying_feedback(
    db: Session,
    *,
    learner_id: int,
    task_id: int,
) -> tuple[str | None, list[Feedback]]:
    # Conversations remain resource-scoped, while normalized learner-turn
    # evidence is aggregated across resources in the same learning package.
    rows = list(
        db.scalars(
            select(Feedback)
            .join(LearningResource, LearningResource.id == Feedback.resource_id)
            .where(
                Feedback.learner_id == learner_id,
                LearningResource.generation_task_id == task_id,
                Feedback.tutoring_message_id.is_not(None),
                Feedback.feedback_intent.in_(INTENT_HYPOTHESES),
                Feedback.decision_confidence >= 0.4,
                Feedback.evidence_status == "eligible",
            )
            .order_by(Feedback.id.desc())
        )
    )
    if len(rows) < 2:
        return None, []
    latest_intent = rows[0].feedback_intent
    if rows[1].feedback_intent != latest_intent:
        rows[0].evidence_status = "conflict"
        rows[1].evidence_status = "conflict"
        db.flush()
        return None, []
    return INTENT_HYPOTHESES.get(str(latest_intent)), list(reversed(rows[:2]))


def _expire_other_package_evidence(
    db: Session, *, learner_id: int, current_task_id: int
) -> None:
    rows = db.scalars(
        select(Feedback)
        .join(LearningResource, LearningResource.id == Feedback.resource_id)
        .where(
            Feedback.learner_id == learner_id,
            Feedback.evidence_status == "eligible",
            LearningResource.generation_task_id != current_task_id,
        )
    )
    for row in rows:
        row.evidence_status = "stale"


def _proposal_trigger_reason(proposal: LearningAdjustmentProposal) -> str:
    if proposal.trigger_source == "automatic":
        return "根据你在本节点多个学习环节中的反馈，建议进行掌握检查"
    return "学习者主动申请掌握检查"


def _serialize_proposal_assessment(
    *,
    proposal: LearningAdjustmentProposal,
    assessment: PathNodeAssessment,
    question: DiagnosticQuestion,
    knowledge: KnowledgeItem | None,
) -> dict[str, Any]:
    payload = {
        "assessment_id": assessment.public_id,
        "adjustment_proposal_id": proposal.public_id,
        "hypothesis_type": proposal.hypothesis_type,
        "trigger_reason": _proposal_trigger_reason(proposal),
        "question_id": question.public_id,
        "knowledge_id": knowledge.public_id if knowledge else "",
        "knowledge_item_id": question.knowledge_item_id,
        "question_type": question.question_type,
        "difficulty": question.difficulty,
        "stem": question.stem,
        "options": question.options_json or [],
        "status": assessment.status,
        "proposal_status": proposal.status,
    }
    if assessment.status == "scored":
        payload.update(dict(assessment.result_json or {}))
        payload["resource_decision"] = proposal.resource_decision
    return payload


def _assessment_for_proposal(
    db: Session,
    *,
    proposal: LearningAdjustmentProposal,
    path: LearningPath,
    node: dict[str, Any],
) -> dict[str, Any]:
    knowledge_ids = [str(value) for value in node.get("knowledge_ids") or []]
    profile = db.get(LearnerProfile, proposal.profile_id)
    source_resource = db.get(LearningResource, proposal.source_resource_id)
    package_task = (
        db.get(GenerationTask, source_resource.generation_task_id)
        if source_resource is not None
        else None
    )
    gate = (
        build_node_gate(db, path=path, profile=profile, package_task=package_task)
        if profile is not None
        else None
    )
    try:
        question, knowledge = select_mastery_question(
            db,
            learner_id=proposal.learner_id,
            domain_code=path.domain_code,
            knowledge_ids=knowledge_ids,
            target_difficulty=int(node.get("target_difficulty") or 3),
            use="mastery_validation",
            node_gate=gate,
            package_task=package_task,
            preferred_knowledge_ids=node.get("focus_knowledge_ids") or [],
        )
    except QuestionBankError as exc:
        raise ValueError(exc.code) from exc
    assessment = PathNodeAssessment(
        public_id=public_id("pathval"),
        learning_path_id=path.id,
        path_node_id=proposal.path_node_id,
        learner_id=proposal.learner_id,
        question_id=question.id,
        adjustment_proposal_id=proposal.id,
        trigger_source=proposal.trigger_source,
        status="pending",
        result_json={},
    )
    db.add(assessment)
    proposal.status = "pending_validation"
    db.flush()
    return _serialize_proposal_assessment(
        proposal=proposal,
        assessment=assessment,
        question=question,
        knowledge=knowledge,
    )


def maybe_create_automatic_assessment(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
    resource: LearningResource,
) -> dict[str, Any] | None:
    learner, path, task, node = _active_context(
        db, session=session, profile=profile, resource=resource
    )
    _expire_other_package_evidence(db, learner_id=learner.id, current_task_id=task.id)
    pending = _pending_proposal(
        db,
        learner_id=learner.id,
        path_id=path.id,
        node_id=str((path.path_json or {}).get("current_node_id")),
    )
    if pending is not None:
        existing = db.scalar(
            select(PathNodeAssessment).where(
                PathNodeAssessment.adjustment_proposal_id == pending.id,
                PathNodeAssessment.status == "pending",
            )
        )
        if existing is None:
            return None
        question = db.get(DiagnosticQuestion, existing.question_id)
        if question is None:
            return None
        knowledge = db.get(KnowledgeItem, question.knowledge_item_id)
        return _serialize_proposal_assessment(
            proposal=pending,
            assessment=existing,
            question=question,
            knowledge=knowledge,
        )
    hypothesis, evidence_rows = _qualifying_feedback(
        db, learner_id=learner.id, task_id=task.id
    )
    if hypothesis is None:
        return None
    evidence_intent = str(evidence_rows[-1].feedback_intent)
    evidence_resource_ids = {row.resource_id for row in evidence_rows}
    supporting_rows = list(
        db.scalars(
            select(Feedback).where(
                Feedback.learner_id == learner.id,
                Feedback.resource_id.in_(evidence_resource_ids),
                Feedback.tutoring_message_id.is_(None),
                Feedback.feedback_intent == evidence_intent,
                Feedback.evidence_status == "supporting_only",
            )
        )
    )
    proposal = LearningAdjustmentProposal(
        public_id=public_id("adjust"),
        learner_id=learner.id,
        profile_id=profile.id,
        learning_path_id=path.id,
        path_node_id=str((path.path_json or {}).get("current_node_id")),
        tutoring_session_id=session.id,
        source_resource_id=resource.id,
        hypothesis_type=hypothesis,
        status="collecting",
        trigger_source="automatic",
        source_feedback_ids_json=[item.id for item in evidence_rows],
        evidence_summary_json={
            "signal_count": len(evidence_rows),
            "intent": evidence_intent,
            "minimum_confidence": min(item.decision_confidence for item in evidence_rows),
            "generation_task_id": task.public_id,
            "tutoring_session_ids": sorted(
                {item.tutoring_session_id for item in evidence_rows if item.tutoring_session_id}
            ),
            "resource_ids": sorted({item.resource_id for item in evidence_rows}),
            "resource_types": sorted(
                {
                    item.resource_type
                    for item in db.scalars(
                        select(LearningResource).where(
                            LearningResource.id.in_(
                                {row.resource_id for row in evidence_rows}
                            )
                        )
                    )
                }
            ),
            "supporting_feedback_ids": [item.id for item in supporting_rows],
        },
        validation_result_json={},
        resource_recommendation_json={},
    )
    db.add(proposal)
    db.flush()
    for row in evidence_rows:
        row.evidence_status = "consumed"
        row.adjustment_proposal_id = proposal.id
    for row in supporting_rows:
        row.evidence_status = "consumed"
        row.adjustment_proposal_id = proposal.id
    return _assessment_for_proposal(db, proposal=proposal, path=path, node=node)


def node_adjustment_context(db: Session, *, session: TutoringSession) -> dict[str, Any]:
    resource = db.get(LearningResource, session.resource_id) if session.resource_id else None
    task = db.get(GenerationTask, resource.generation_task_id) if resource else None
    if resource is None or task is None:
        return {
            "node_adjustment_state": "none",
            "pending_assessment": None,
            "node_adjustment_result": None,
            "evidence_scope": None,
            "node_gate": None,
        }
    task_proposal = db.scalar(
        select(LearningAdjustmentProposal)
        .join(
            LearningResource,
            LearningResource.id == LearningAdjustmentProposal.source_resource_id,
        )
        .where(
            LearningAdjustmentProposal.learner_id == session.learner_id,
            LearningAdjustmentProposal.tutoring_session_id == session.id,
            LearningResource.generation_task_id == task.id,
        )
        .order_by(LearningAdjustmentProposal.id.desc())
    )
    if task_proposal is not None and task_proposal.status in {
        "resource_pending",
        "resource_started",
        "resource_skipped",
    }:
        scored_assessment = db.scalar(
            select(PathNodeAssessment).where(
                PathNodeAssessment.adjustment_proposal_id == task_proposal.id,
                PathNodeAssessment.status == "scored",
            )
        )
        question = (
            db.get(DiagnosticQuestion, scored_assessment.question_id)
            if scored_assessment
            else None
        )
        result = (
            _serialize_proposal_assessment(
                proposal=task_proposal,
                assessment=scored_assessment,
                question=question,
                knowledge=(
                    db.get(KnowledgeItem, question.knowledge_item_id) if question else None
                ),
            )
            if scored_assessment is not None and question is not None
            else dict(task_proposal.validation_result_json or {})
        )
        return {
            "node_adjustment_state": "confirmed",
            "pending_assessment": None,
            "node_adjustment_result": result,
            "evidence_scope": {
                "path_node_id": task_proposal.path_node_id,
                "path_node_title": None,
                "generation_task_id": task.public_id,
            },
            "node_gate": result.get("node_gate") if isinstance(result, dict) else None,
        }
    path = db.scalar(
        select(LearningPath)
        .where(
            LearningPath.learner_id == session.learner_id,
            LearningPath.domain_code == task.domain_code,
            LearningPath.status == "active",
        )
        .order_by(LearningPath.created_at.desc(), LearningPath.id.desc())
    )
    payload = normalize_learning_path(path) if path else {}
    node_id = payload.get("current_node_id")
    node = (payload.get("node_states") or {}).get(node_id) if node_id else None
    if (
        path is None
        or not isinstance(node, dict)
        or task.learning_path_id != path.id
        or task.path_node_id != node_id
        or not task.is_current_package
        or not resource.is_current
    ):
        return {
            "node_adjustment_state": "none",
            "pending_assessment": None,
            "node_adjustment_result": None,
            "evidence_scope": None,
            "node_gate": None,
        }
    proposal = db.scalar(
        select(LearningAdjustmentProposal)
        .where(
            LearningAdjustmentProposal.learner_id == session.learner_id,
            LearningAdjustmentProposal.tutoring_session_id == session.id,
            LearningAdjustmentProposal.learning_path_id == path.id,
            LearningAdjustmentProposal.path_node_id == node_id,
        )
        .order_by(LearningAdjustmentProposal.id.desc())
    )
    pending_assessment = None
    state = "collecting"
    if proposal is not None and proposal.status == "pending_validation":
        assessment = db.scalar(
            select(PathNodeAssessment).where(
                PathNodeAssessment.adjustment_proposal_id == proposal.id,
                PathNodeAssessment.status == "pending",
            )
        )
        question = db.get(DiagnosticQuestion, assessment.question_id) if assessment else None
        knowledge = db.get(KnowledgeItem, question.knowledge_item_id) if question else None
        if assessment is not None and question is not None:
            pending_assessment = _serialize_proposal_assessment(
                proposal=proposal,
                assessment=assessment,
                question=question,
                knowledge=knowledge,
            )
            state = "pending_validation"
    active_profile = db.get(LearnerProfile, path.profile_id)
    return {
        "node_adjustment_state": state,
        "pending_assessment": pending_assessment,
        "node_adjustment_result": None,
        "evidence_scope": {
            "path_node_id": node_id,
            "path_node_title": node.get("title") or node.get("knowledge_id"),
            "generation_task_id": task.public_id,
        },
        "node_gate": (
            build_node_gate(db, path=path, profile=active_profile, package_task=task)
            if active_profile is not None
            else None
        ),
    }


def request_mastery_assessment(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
) -> dict[str, Any]:
    resource = db.get(LearningResource, session.resource_id) if session.resource_id else None
    if resource is None:
        raise ValueError("tutoring_session_resource_not_found")
    learner, path, _task, node = _active_context(
        db, session=session, profile=profile, resource=resource
    )
    pending = _pending_proposal(
        db,
        learner_id=learner.id,
        path_id=path.id,
        node_id=str((path.path_json or {}).get("current_node_id")),
    )
    if pending is not None:
        raise ValueError("learning_adjustment_already_pending")
    proposal = LearningAdjustmentProposal(
        public_id=public_id("adjust"),
        learner_id=learner.id,
        profile_id=profile.id,
        learning_path_id=path.id,
        path_node_id=str((path.path_json or {}).get("current_node_id")),
        tutoring_session_id=session.id,
        source_resource_id=resource.id,
        hypothesis_type="mastery_up",
        status="collecting",
        trigger_source="manual",
        source_feedback_ids_json=[],
        evidence_summary_json={"signal_count": 1, "intent": "mastery_check_requested"},
        validation_result_json={},
        resource_recommendation_json={},
    )
    db.add(proposal)
    db.flush()
    assessment = _assessment_for_proposal(db, proposal=proposal, path=path, node=node)
    db.add(
        TutoringMessage(
            public_id=public_id("msg"),
            session_id=session.id,
            sender="tutoring_agent",
            message_type="assessment",
            content="学习者主动申请掌握检查",
            metadata_json={"assessment": assessment, "stream_status": "completed"},
        )
    )
    db.flush()
    return assessment


def _path_snapshots(
    path: LearningPath, profile: LearnerProfile
) -> tuple[LearningPathSnapshot, LearningPathNodeSnapshot | None]:
    payload = normalize_learning_path(path)
    snapshot = profile_snapshot(profile)
    average = sum(snapshot.ability_scores.model_dump().values()) / 5
    difficulty = max(1, min(5, round(average / 20)))
    nodes = [
        LearningPathNodeSnapshot(
            path_node_id=str(node["path_node_id"]),
            knowledge_ids=list(node.get("knowledge_ids") or []),
            focus_knowledge_ids=list(node.get("focus_knowledge_ids") or []),
            title=str(node.get("title") or "学习单元"),
            path_order=int(node.get("path_order") or 1),
            target_difficulty=difficulty,
            learning_objective=str(node.get("learning_objective") or "掌握本单元知识"),
            recommendation_reason=str(
                node.get("recommendation_reason") or "根据画像与知识关系规划。"
            ),
            prerequisite_knowledge_ids=list(node.get("prerequisite_knowledge_ids") or []),
        )
        for node in (payload.get("node_states") or {}).values()
        if isinstance(node, dict)
    ]
    current_id = payload.get("current_node_id")
    current = next((item for item in nodes if item.path_node_id == current_id), None)
    return LearningPathSnapshot(
        path_id=path.public_id,
        nodes=sorted(nodes, key=lambda item: item.path_order),
        current_node_id=current.path_node_id if current else None,
    ), current


def _analyze_profile(
    db: Session,
    *,
    proposal: LearningAdjustmentProposal,
    profile: LearnerProfile,
    path: LearningPath,
    resource: LearningResource,
    feedback: Feedback,
    record: AnswerRecord,
    question: DiagnosticQuestion,
    evidence_records: list[AnswerRecord] | None = None,
) -> tuple[LearnerProfile, LearningPath | None, Any, dict[str, Any]]:
    evidence_id = f"answer_record:{record.id}"
    knowledge = db.get(KnowledgeItem, question.knowledge_item_id)
    learner = db.get(Learner, proposal.learner_id)
    if knowledge is None or learner is None:
        raise ValueError("learning_adjustment_knowledge_missing")
    formal_records = evidence_records or [record]
    evidences: list[EvidenceRef] = []
    assessments: list[KnowledgeAssessment] = []
    evidence_classes: dict[str, str] = {}
    for index, formal_record in enumerate(formal_records):
        formal_question = db.get(DiagnosticQuestion, formal_record.question_id)
        formal_knowledge = (
            db.get(KnowledgeItem, formal_question.knowledge_item_id)
            if formal_question is not None
            else None
        )
        if (
            formal_question is None
            or formal_knowledge is None
            or formal_question.status != "active"
            or formal_question.domain_code != profile.domain_code
            or formal_knowledge.domain_code != profile.domain_code
        ):
            continue
        formal_evidence_id = f"answer_record:{formal_record.id}"
        summary = formal_record.answer_summary_json or {}
        evidence_class = (
            "auxiliary"
            if str(summary.get("evidence_type") or "") == "mistake_correction"
            else "core"
        )
        evidence_classes[formal_evidence_id] = evidence_class
        evidences.append(
            EvidenceRef(
                evidence_id=formal_evidence_id,
                evidence_type=EvidenceType.SCORED_QUIZ,
                summary="正式验证已由服务端评分",
                knowledge_id=formal_knowledge.public_id,
                source_ref_id=formal_question.public_id,
                confidence=float(formal_record.confidence or 0.0),
                confirmed=True,
            )
        )
        assessments.append(
            KnowledgeAssessment(
                assessment_id=f"{proposal.public_id}:{index + 1}",
                evidence_id=formal_evidence_id,
                knowledge_id=formal_knowledge.public_id,
                score=float(formal_record.score),
                difficulty=formal_question.difficulty,
                attempted=True,
                confidence=float(formal_record.confidence or 0.0),
            )
        )
    path_snapshot, current_node = _path_snapshots(path, profile)
    context = TaskContext(
        task_id=proposal.public_id,
        session_id=proposal.public_id,
        trigger_type="resource_feedback",
        execution_mode="auto",
        learner_id=learner.public_id,
        profile_id=profile.public_id,
        domain_code=profile.domain_code,
        resource_types=[resource.resource_type],
        learning_goal="根据导学交互和正式微验证更新学习画像",
        resource_id=resource.public_id,
        feedback_id=str(feedback.id),
        tutoring_session_id=str(proposal.tutoring_session_id),
    )
    runtime = load_domain_runtime(db, profile.domain_code)
    if runtime.profile_config is None:
        raise ValueError("profile_runtime_not_ready")
    run = AgentRun(
        generation_task_id=None,
        agent_name="profile_analysis_agent",
        status="running",
        input_summary_json={
            "proposal_id": proposal.public_id,
            "knowledge_id": knowledge.public_id,
            "hypothesis_type": proposal.hypothesis_type,
        },
        output_summary_json={},
        prompt_version=PROMPT_VERSION,
        prompt_hash=prompt_hash("profile"),
        contract_version=AGENT_CONTRACT_VERSION,
    )
    db.add(run)
    db.add(
        AgentMessageRecord(
            session_id=proposal.public_id,
            task_id=proposal.public_id,
            sender="orchestrator_agent",
            receiver="profile_analysis_agent",
            message_type="command",
            payload_summary_json={"hypothesis_type": proposal.hypothesis_type},
        )
    )
    started_at = time.perf_counter()
    with collect_model_calls() as collector:
        analysis = ProfileAnalysisAgent(runtime.profile_config).execute(
            AnalyzeProfileInput(
                task_id=proposal.public_id,
                context=context,
                current_profile=profile_snapshot(profile),
                learning_path=path_snapshot,
                current_path_node=current_node,
                feedback_evidence=evidences,
                recommended_action=(
                    RecommendedAction.CHALLENGE
                    if proposal.hypothesis_type == "mastery_up"
                    else RecommendedAction.EXPLAIN
                ),
                knowledge_assessments=assessments,
            )
        )
    calls = collector.snapshot()
    run.status = "completed"
    run.output_summary_json = {
        "proposal_id": proposal.public_id,
        "profile_update_required": analysis.profile_update_required,
        "changed_dimensions": analysis.changed_dimensions,
    }
    run.llm_calls = len(calls)
    run.tokens_input = sum(item["tokens_input"] for item in calls)
    run.tokens_output = sum(item["tokens_output"] for item in calls)
    run.tokens_used = run.tokens_input + run.tokens_output
    run.model_name = calls[0]["model_name"] if calls else None
    run.duration_ms = round((time.perf_counter() - started_at) * 1000)
    db.add(
        AgentMessageRecord(
            session_id=proposal.public_id,
            task_id=proposal.public_id,
            sender="profile_analysis_agent",
            receiver="orchestrator_agent",
            message_type="result",
            payload_summary_json={
                "profile_update_required": analysis.profile_update_required,
                "changed_dimensions": analysis.changed_dimensions,
            },
        )
    )
    previous_state = (profile.ability_profile_json or {}).get(STATE_KEY)
    knowledge_state = build_knowledge_state(
        config=runtime.profile_config,
        assessments=assessments,
        evidence=evidences,
        previous_state=previous_state,
        evidence_class_by_id=evidence_classes,
    )
    analysis, projection = project_analysis_with_knowledge_state(
        analysis=analysis,
        state=knowledge_state,
        previous_state=previous_state,
        config=runtime.profile_config,
        context=profile.context_snapshot_json or {},
    )
    before_snapshot = profile_snapshot(profile)
    before_weak = next(
        (item for item in before_snapshot.weak_knowledge if item.knowledge_id == knowledge.public_id),
        None,
    )
    after_item = knowledge_state["items"][knowledge.public_id]
    after_weak = next(
        (item for item in analysis.profile.weak_knowledge if item.knowledge_id == knowledge.public_id),
        None,
    )
    before_scores = before_snapshot.ability_scores.model_dump(mode="json")
    after_scores = analysis.profile.ability_scores.model_dump(mode="json")
    change_summary = {
        "knowledge_id": knowledge.public_id,
        "knowledge_name": knowledge.name,
        "before_state": (
            (previous_state or {}).get("items", {}).get(knowledge.public_id, {}).get("status")
            or (before_weak.mastery_type.value if before_weak else "unassessed")
        ),
        "after_state": after_item["status"],
        "before_weakness_level": before_weak.weakness_level if before_weak else None,
        "after_weakness_level": after_weak.weakness_level if after_weak else None,
        "removed_from_weak_knowledge": before_weak is not None and after_weak is None,
        "removed_from_blind_spots": (
            knowledge.public_id in before_snapshot.blind_spot_ids
            and knowledge.public_id not in analysis.profile.blind_spot_ids
        ),
        "evidence_ids": [evidence_id],
        "path_node_id": proposal.path_node_id,
        "profile_changed": analysis.profile_update_required,
        "affected_knowledge_ids": list(
            dict.fromkeys(
                [
                    *list(projection.get("changed_knowledge_ids") or []),
                    knowledge.public_id,
                ]
            )
        ),
        "ability_score_changes": {
            key: {"before": before_scores[key], "after": after_scores[key]}
            for key in before_scores
            if before_scores[key] != after_scores[key]
        },
    }
    change_summary["ability_summary"] = (
        "高层能力已更新" if change_summary["ability_score_changes"] else "高层能力保持不变"
    )
    internal_updates = {
        STATE_KEY: knowledge_state,
        "dimension_status": projection["dimension_status"],
        "learning_speed_evidence": projection.get("learning_speed_evidence", {}),
        "evidence_profile": {
            "version": runtime.profile_config.subsequent_rule_version,
            "status": projection.get("evidence_status", "accumulating"),
            "coverage": knowledge_state.get("coverage", {}),
            "message": analysis.decision_reason,
        },
    }
    if not analysis.profile_update_required:
        # Accumulate evidence in the current profile's private state without
        # creating a visible profile version, changing its radar or proposing
        # resources.  The next independent evidence will build from this.
        profile.ability_profile_json = {
            **dict(profile.ability_profile_json or {}),
            **internal_updates,
        }
        db.flush()
        next_profile, next_path = profile, None
    else:
        next_profile, next_path = persist_profile_revision(
        db,
        original=profile,
        analysis=analysis,
        trigger_feedback_id=feedback.id,
        internal_profile_updates=internal_updates,
    )
    change_summary["original_profile_id"] = profile.public_id
    change_summary["original_profile_version"] = profile.profile_version
    change_summary["resulting_profile_id"] = next_profile.public_id
    change_summary["resulting_profile_version"] = next_profile.profile_version
    return next_profile, next_path, analysis, change_summary


def answer_adjustment_assessment(
    db: Session,
    *,
    session: TutoringSession,
    profile: LearnerProfile,
    assessment_id: str,
    answer: Any,
) -> tuple[AnswerRecord, Feedback, dict[str, Any]]:
    assessment = db.scalar(
        select(PathNodeAssessment)
        .where(PathNodeAssessment.public_id == assessment_id)
        .with_for_update()
    )
    proposal = (
        db.get(LearningAdjustmentProposal, assessment.adjustment_proposal_id)
        if assessment and assessment.adjustment_proposal_id
        else None
    )
    if (
        assessment is None
        or proposal is None
        or proposal.learner_id != session.learner_id
        or proposal.tutoring_session_id != session.id
    ):
        raise ValueError("learning_adjustment_assessment_not_found")
    feedback_id = (proposal.source_feedback_ids_json or [None])[-1]
    feedback = db.get(Feedback, feedback_id) if feedback_id is not None else None
    if feedback is None:
        feedback = Feedback(
            resource_id=proposal.source_resource_id,
            learner_id=proposal.learner_id,
            feedback_type="mastery_check",
            feedback_summary_json={"proposal_id": proposal.public_id},
            triggered_action="ask_follow_up",
            comment="主动申请掌握检查",
            tutoring_session_id=session.id,
            feedback_intent="too_easy",
            recommended_action="ask_follow_up",
            decision_confidence=0.4,
            decision_reason="等待正式微验证",
        )
        db.add(feedback)
        db.flush()
        proposal.source_feedback_ids_json = [feedback.id]
    if assessment.status == "scored" and assessment.answer_record_id:
        record = db.get(AnswerRecord, assessment.answer_record_id)
        if record is None:
            raise ValueError("learning_adjustment_answer_missing")
        return record, feedback, dict(assessment.result_json or {})
    if proposal.status != "pending_validation":
        raise ValueError("learning_adjustment_proposal_stale")
    question = db.get(DiagnosticQuestion, assessment.question_id)
    path = db.get(LearningPath, proposal.learning_path_id)
    resource = db.get(LearningResource, proposal.source_resource_id)
    submitting_resource = (
        db.get(LearningResource, session.resource_id) if session.resource_id else None
    )
    if question is None or path is None or resource is None or path.status != "active":
        proposal.status = "stale"
        raise ValueError("learning_adjustment_proposal_stale")
    if (
        submitting_resource is None
        or submitting_resource.generation_task_id != resource.generation_task_id
        or (path.path_json or {}).get("current_node_id") != proposal.path_node_id
    ):
        raise ValueError("learning_adjustment_assessment_context_stale")
    try:
        selected = int(answer)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_single_choice_answer") from exc
    if selected < 0 or selected >= len(question.options_json or []):
        raise ValueError("invalid_single_choice_answer")
    correct = int((question.answer_key_json or {}).get("correct_option", -1))
    is_correct = selected == correct
    score = 1.0 if is_correct else 0.0
    confirmed = (
        proposal.hypothesis_type == "mastery_up" and is_correct
    ) or (proposal.hypothesis_type == "support_down" and not is_correct)
    record = AnswerRecord(
        learner_id=proposal.learner_id,
        question_id=question.id,
        knowledge_item_id=question.knowledge_item_id,
        session_id=assessment.public_id,
        answer_text=str(selected),
        score=score,
        is_correct=is_correct,
        scoring_status="scored",
        scoring_method="deterministic",
        confidence=0.9,
        answer_summary_json={
            "evidence_type": "path_validation",
            "evidence_role": "validation",
            "assessment_id": assessment.public_id,
            "adjustment_proposal_id": proposal.public_id,
            "contract_evidence_type": "scored_quiz",
            "confirmed": True,
            "confidence": 0.9,
            "generation_task_id": db.get(GenerationTask, resource.generation_task_id).public_id,
            "path_node_id": proposal.path_node_id,
            "consumed_by_profile_id": None,
        },
    )
    db.add(record)
    db.flush()
    evidence_id = f"answer_record:{record.id}"
    package_task = db.get(GenerationTask, resource.generation_task_id)
    preliminary_gate = build_node_gate(
        db,
        path=path,
        profile=profile,
        package_task=package_task,
    )
    knowledge = db.get(KnowledgeItem, question.knowledge_item_id)
    knowledge_id = knowledge.public_id if knowledge else None
    knowledge_progress = next(
        (
            item
            for item in preliminary_gate.get("knowledge_progress") or []
            if item.get("knowledge_id") == knowledge_id
        ),
        None,
    )
    mastery_evidence_ready = bool(
        is_correct
        and knowledge_progress
        and knowledge_progress.get("eligible_evidence_count", 0)
        >= knowledge_progress.get("required_evidence_count", 2)
        and knowledge_progress.get("has_corroborating_evidence")
        and knowledge_progress.get("has_target_difficulty_evidence")
    )
    confirmed = (
        proposal.hypothesis_type == "mastery_up" and mastery_evidence_ready
    ) or (proposal.hypothesis_type == "support_down" and not is_correct)
    decision = "evidence_recorded" if is_correct else "hypothesis_rejected"
    profile_changed = False
    resulting_profile = profile
    resulting_path = path
    completed_node_id = None
    profile_change_summary = None
    if confirmed:
        evidence_records = None
        if proposal.hypothesis_type == "mastery_up" and knowledge_progress:
            record_ids = [
                int(value.split(":", 1)[1])
                for value in knowledge_progress.get("evidence_ids") or []
                if str(value).startswith("answer_record:")
            ]
            evidence_records = list(
                db.scalars(
                    select(AnswerRecord)
                    .where(AnswerRecord.id.in_(record_ids))
                    .order_by(AnswerRecord.created_at, AnswerRecord.id)
                )
            )
        resulting_profile, revised_path, _analysis, profile_change_summary = _analyze_profile(
            db,
            proposal=proposal,
            profile=profile,
            path=path,
            resource=resource,
            feedback=feedback,
            record=record,
            question=question,
            evidence_records=evidence_records,
        )
        profile_changed = resulting_profile.id != profile.id
        if revised_path is not None:
            resulting_path = revised_path
        node_gate = build_node_gate(
            db,
            path=resulting_path,
            profile=resulting_profile,
            package_task=package_task,
        )
        if proposal.hypothesis_type == "mastery_up" and node_gate["can_advance"]:
            completed_node_id = proposal.path_node_id
            _advance_path_node(
                db,
                path=resulting_path,
                node_id=completed_node_id,
                evidence_ids=[
                    evidence_id
                    for item in node_gate.get("knowledge_progress") or []
                    for evidence_id in item.get("evidence_ids") or []
                ],
            )
            decision = "confirmed_mastery"
        else:
            decision = "confirmed_support_need" if proposal.hypothesis_type == "support_down" else "evidence_recorded"
        current_node_id = (resulting_path.path_json or {}).get("current_node_id")
        node_gate["completed_node_id"] = completed_node_id
        node_gate["current_node_id"] = current_node_id
        profile_change_summary = dict(profile_change_summary or {})
        profile_change_summary.update(
            {
                "interaction_evidence_ids": [
                    f"feedback:{feedback_id}"
                    for feedback_id in (proposal.source_feedback_ids_json or [])
                ],
                "completed_node_id": completed_node_id,
                "current_node_id": current_node_id,
            }
        )
        recommendation = None
        if profile_changed:
            affected_ids = list(
                dict.fromkeys(
                    [
                        *list(profile_change_summary.get("affected_knowledge_ids") or []),
                        *list(node_gate.get("unmastered_knowledge_ids") or []),
                        *([knowledge_id] if knowledge_id else []),
                    ]
                )
            )
            recommendation = decide_resource_matching(
                proposal_id=proposal.public_id,
                path=resulting_path,
                node_gate=node_gate,
                package_task=package_task,
                source_resource=resource,
                affected_knowledge_ids=affected_ids,
                hypothesis_type=proposal.hypothesis_type,
                node_advanced=completed_node_id is not None,
            )
            if recommendation["decision_type"] == "future_path_reprioritize":
                reprioritize_future_nodes(
                    resulting_path,
                    affected_knowledge_ids=affected_ids,
                    reason=str(recommendation["reason"]),
                )
            proposal.status = (
                "resource_pending"
                if recommendation["requires_confirmation"]
                else "evidence_recorded"
            )
        else:
            proposal.status = "evidence_recorded"
        proposal.resulting_profile_id = resulting_profile.id
        proposal.resulting_learning_path_id = resulting_path.id
        proposal.resource_recommendation_json = recommendation or {}
    else:
        current_node_id = (path.path_json or {}).get("current_node_id")
        recommendation = None
        node_gate = preliminary_gate
        proposal.status = "evidence_recorded" if is_correct else "rejected"
    result = {
        "adjustment_proposal_id": proposal.public_id,
        "hypothesis_type": proposal.hypothesis_type,
        "decision": decision,
        "score": score,
        "is_correct": is_correct,
        "confirmed": confirmed,
        "profile_changed": profile_changed,
        "resulting_profile_id": resulting_profile.public_id,
        "resulting_path_id": resulting_path.public_id,
        "completed_node_id": completed_node_id,
        "current_node_id": current_node_id,
        "resource_recommendation": recommendation,
        "node_gate": node_gate,
        "profile_change_summary": profile_change_summary,
        "decision_reason": {
            "confirmed_mastery": "已确认掌握，学习路线已推进",
            "confirmed_support_need": "已确认需要补强，当前学习节点保持不变",
            "evidence_recorded": "本次正式证据已记录，尚未达到画像或节点更新门槛",
            "hypothesis_rejected": "验证结果与近期反馈不一致，画像和路线保持不变",
        }[decision],
        "submitted_option": selected,
    }
    if is_correct:
        result.update({
            "correct_option": correct,
            "correct_answer": (question.options_json or [])[correct],
            "explanation": str((question.answer_key_json or {}).get("explanation") or ""),
        })
    assessment.answer_record_id = record.id
    assessment.status = "scored"
    assessment.score = score
    assessment.passed = confirmed
    assessment.result_json = result
    proposal.validation_result_json = result
    for pending_feedback in db.scalars(
        select(Feedback)
        .join(LearningResource, LearningResource.id == Feedback.resource_id)
        .where(
            Feedback.learner_id == proposal.learner_id,
            Feedback.evidence_status == "eligible",
            LearningResource.generation_task_id == resource.generation_task_id,
        )
    ):
        pending_feedback.evidence_status = "stale"
    knowledge = db.get(KnowledgeItem, question.knowledge_item_id)
    feedback.profile_change_evidence_json = [
        *list(feedback.profile_change_evidence_json or []),
        {
            "evidence_id": evidence_id,
            "evidence_type": "scored_quiz",
            "knowledge_id": knowledge.public_id if knowledge else None,
            "confirmed": confirmed,
            "confidence": 0.9,
        },
    ]
    feedback.profile_update_required = profile_changed
    feedback.decision_reason = result["decision_reason"]
    feedback.decision_confidence = 0.9
    message = None
    for candidate in db.scalars(
        select(TutoringMessage)
        .where(TutoringMessage.session_id == session.id)
        .order_by(TutoringMessage.id.desc())
    ):
        metadata = dict(candidate.metadata_json or {})
        embedded = metadata.get("assessment") or {}
        if embedded.get("assessment_id") == assessment.public_id:
            message = candidate
            break
    if message is not None:
        metadata = dict(message.metadata_json or {})
        metadata["assessment"] = {
            **dict(metadata.get("assessment") or {}),
            **result,
            "status": "scored",
        }
        message.metadata_json = metadata
    db.commit()
    return record, feedback, result


def decide_proposal_resource(
    db: Session,
    *,
    proposal_id: str,
    learner_public_id: str,
    decision: str,
) -> tuple[dict[str, Any], GenerationTask | None]:
    proposal = db.scalar(
        select(LearningAdjustmentProposal)
        .where(LearningAdjustmentProposal.public_id == proposal_id)
        .with_for_update()
    )
    learner = db.get(Learner, proposal.learner_id) if proposal else None
    if proposal is None or learner is None or learner.public_id != learner_public_id:
        raise ValueError("learning_adjustment_proposal_not_found")
    if decision not in {"generate", "skip"}:
        raise ValueError("invalid_resource_decision")

    # A learner may dismiss an already-shown recommendation even if the path
    # has since advanced. Staleness only prevents creating a new resource.
    if decision == "skip":
        if proposal.status == "resource_skipped":
            return {"proposal_id": proposal.public_id, "decision": "skip", "task_id": None}, None
        if proposal.status in {"resource_pending", "resource_started", "stale"}:
            proposal.status = "resource_skipped"
            proposal.resource_decision = "skip"
            db.commit()
            return {"proposal_id": proposal.public_id, "decision": "skip", "task_id": None}, None
        raise ValueError("learning_adjustment_proposal_stale")

    existing = db.get(GenerationTask, proposal.generation_task_id) if proposal.generation_task_id else None
    if proposal.status not in {"resource_pending", "resource_started"}:
        raise ValueError("learning_adjustment_proposal_stale")
    recommendation = proposal.resource_recommendation_json or {}
    decision_type = str(recommendation.get("decision_type") or "")
    if decision_type in {"no_generation", "future_path_reprioritize"}:
        raise ValueError("learning_adjustment_has_no_resource_action")
    path = db.get(LearningPath, proposal.resulting_learning_path_id or proposal.learning_path_id)
    profile = db.get(LearnerProfile, proposal.resulting_profile_id or proposal.profile_id)
    current_node_id = (path.path_json or {}).get("current_node_id") if path else None
    if path is None or profile is None or path.status != "active" or current_node_id != recommendation.get("path_node_id"):
        proposal.status = "stale"
        db.commit()
        raise ValueError("learning_adjustment_proposal_stale")
    resource_types = list(recommendation.get("resource_types") or [])
    is_node_advancement = decision_type == "next_stage" or recommendation.get("mode") == "next_node"
    if is_node_advancement and set(resource_types) != NODE_ADVANCEMENT_RESOURCE_TYPES:
        raise ValueError("node_advancement_resource_types_invalid")
    basis = resolve_node_generation_basis(
        db,
        path=path,
        path_node_id=current_node_id,
        profile=profile,
        resource_types=resource_types,
    )
    if "graded_quiz" in resource_types:
        quiz_preflight = graded_quiz_preflight(
            db,
            domain_code=path.domain_code,
            target_knowledge_ids=list(
                (basis.get("resource_knowledge_targets") or {}).get("graded_quiz") or []
            ),
            focus_knowledge_ids=list(basis.get("focus_knowledge_ids") or []),
            target_difficulty=int(basis.get("target_difficulty") or 3),
            profile_type=profile_snapshot(profile).profile_type.value,
        )
        if not quiz_preflight["ready"]:
            raise ValueError("graded_quiz_question_bank_not_ready")
    if existing is not None:
        if not is_node_advancement or not _node_advancement_task_needs_recovery(
            db, task=existing, resource_types=resource_types
        ):
            return {
                "proposal_id": proposal.public_id,
                "decision": "generate",
                "task_id": existing.public_id,
                "recovered": False,
            }, existing

    if decision_type == "remedial":
        resource = db.get(LearningResource, proposal.source_resource_id)
        feedback = db.get(Feedback, (proposal.source_feedback_ids_json or [None])[-1])
        if resource is None or feedback is None:
            raise ValueError("learning_adjustment_source_missing")
        task = create_feedback_task(
            db,
            learner=learner,
            profile=profile,
            resource=resource,
            feedback=feedback,
            resource_types=resource_types,
        )
        task.learning_path_id = path.id
        task.path_node_id = current_node_id
    else:
        resource = db.get(LearningResource, proposal.source_resource_id)
        feedback = db.get(Feedback, (proposal.source_feedback_ids_json or [None])[-1])
        if resource is None or feedback is None:
            raise ValueError("learning_adjustment_source_missing")
        # A learner-confirmed challenge or next-node package is a new generation
        # request, not a second feedback interpretation. It retains the source
        # feedback chain for audit but enters the normal generation graph.
        task = GenerationTask(
            public_id=public_id("task"),
            learner_id=learner.id,
            profile_id=profile.id,
            learning_path_id=path.id,
            path_node_id=current_node_id,
            domain_code=path.domain_code,
            status="pending",
            resource_types_json=resource_types,
            revision_count=0,
            decision="pending",
            trigger_type="initial_generation",
            execution_mode="auto",
            learning_goal=(
                (
                    f"掌握验证已确认；为学习路线当前节点 {current_node_id} "
                    "生成更高难度的挑战练习。"
                    if decision_type == "challenge"
                    else f"掌握验证已确认；基于画像 V{profile.profile_version} 为学习路线当前节点 "
                    f"{current_node_id} 生成完整学习包"
                )[:512]
            ),
            source_resource_id=resource.id,
            source_feedback_id=feedback.id,
            source_task_id=resource.generation_task_id,
            event_type=(
                NODE_ADVANCEMENT_EVENT_TYPE if is_node_advancement else "challenge_task"
            ),
            progress=0,
        )
        db.add(task)
        db.flush()
    bind_node_generation_targets(task, basis)
    proposal.status = "resource_started"
    proposal.resource_decision = "generate"
    proposal.generation_task_id = task.id
    db.commit()
    return {
        "proposal_id": proposal.public_id,
        "decision": "generate",
        "task_id": task.public_id,
        "recovered": existing is not None,
    }, task


def _node_advancement_task_needs_recovery(
    db: Session,
    *,
    task: GenerationTask,
    resource_types: list[str],
) -> bool:
    """Whether a confirmed next-node package needs a fresh replacement task.

    Historical proposals may point at a feedback task which completed with
    ``no_change`` and no resources.  A failed or incomplete node-advancement
    task is also safe to replace: the proposal switches to the new task while
    the failed task and its original feedback links remain intact for audit.
    """
    expected = set(resource_types)
    resources = list(
        db.scalars(
            select(LearningResource).where(LearningResource.generation_task_id == task.id)
        )
    )
    passed_types = {
        resource.resource_type for resource in resources if resource.review_status == "passed"
    }
    if task.status in {"pending", "retry_pending", "running", "revision_required"}:
        return False
    if task.status == "completed" and task.decision == "completed" and passed_types == expected:
        return False
    if task.status == "completed" and task.decision == "no_change" and not resources:
        return True
    return task.status == "failed" or passed_types != expected


def pending_resource_proposals(
    db: Session, *, learner_id: int, domain_code: str
) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(LearningAdjustmentProposal)
            .join(LearningPath, LearningPath.id == LearningAdjustmentProposal.resulting_learning_path_id)
            .where(
                LearningAdjustmentProposal.learner_id == learner_id,
                LearningAdjustmentProposal.status.in_(
                    {"resource_pending", "resource_started", "evidence_recorded"}
                ),
                LearningPath.domain_code == domain_code,
                LearningPath.status == "active",
            )
            .order_by(LearningAdjustmentProposal.id.desc())
        )
    )
    result: list[dict[str, Any]] = []
    for item in rows:
        recommendation = dict(item.resource_recommendation_json or {})
        task = db.get(GenerationTask, item.generation_task_id) if item.generation_task_id else None
        profile = db.get(LearnerProfile, item.resulting_profile_id or item.profile_id)
        source_resource = db.get(LearningResource, item.source_resource_id)
        source_task = (
            db.get(GenerationTask, source_resource.generation_task_id)
            if source_resource is not None
            else None
        )
        path = db.get(LearningPath, item.resulting_learning_path_id or item.learning_path_id)
        resource_types = list(recommendation.get("resource_types") or [])
        recoverable = bool(
            task is not None
            and recommendation.get("mode") == "next_node"
            and _node_advancement_task_needs_recovery(
                db, task=task, resource_types=resource_types
            )
        )
        package_task = task if task is not None and task.status == "completed" else source_task
        node_gate = None
        if path is not None and profile is not None:
            node_gate = build_node_gate(
                db,
                path=path,
                profile=profile,
                package_task=package_task,
            )
        route_reason = _route_gate_message(node_gate)
        source_resources = []
        if source_task is not None:
            source_resources = [
                {
                    "resource_id": resource.public_id,
                    "resource_type": resource.resource_type,
                    "title": resource.title,
                }
                for _member, resource in package_member_rows(db, source_task)
                if resource.resource_type in resource_types
            ]
        previous_profile = (
            db.get(LearnerProfile, profile.previous_profile_id)
            if profile is not None and profile.previous_profile_id is not None
            else None
        )
        result.append(
            {
                "proposal_id": item.public_id,
                "hypothesis_type": item.hypothesis_type,
                "status": item.status,
                "resource_recommendation": recommendation,
                "profile_version": profile.profile_version if profile is not None else None,
                "previous_profile_version": previous_profile.profile_version if previous_profile else None,
                "current_node": {
                    "path_node_id": recommendation.get("path_node_id"),
                    "title": (
                        ((path.path_json or {}).get("node_states") or {})
                        .get(recommendation.get("path_node_id"), {})
                        .get("title")
                        if path is not None
                        else None
                    ),
                },
                "affected_resources": source_resources,
                "node_gate": node_gate,
                "route_message": route_reason,
                "decision": (item.validation_result_json or {}).get("decision"),
                "generation_task": (
                    {
                        "task_id": task.public_id,
                        "status": task.status,
                        "decision": task.decision,
                        "failure_reason": task.failure_reason or None,
                        "event_type": task.event_type,
                        "published_resource_types": sorted(
                            resource.resource_type
                            for resource in db.scalars(
                                select(LearningResource).where(
                                    LearningResource.generation_task_id == task.id,
                                    LearningResource.review_status == "passed",
                                )
                            )
                        ),
                    }
                    if task is not None
                    else None
                ),
                "recovery_available": recoverable,
            }
        )
    return result


def _route_gate_message(node_gate: dict[str, Any] | None) -> dict[str, str] | None:
    if node_gate is None:
        return None
    reason = str(node_gate.get("reason") or "")
    messages = {
        "NODE_REQUIREMENTS_MET": ("当前节点已满足推进条件。", "可以继续确认下一学习节点。"),
        "GRADED_QUIZ_REQUIRED": (
            "路线暂未推进：当前节点尚未完成分阶测验。",
            "完成当前分阶测验后，系统会继续核验掌握证据和错题状态。",
        ),
        "BLOCKING_MISTAKES_REMAIN": (
            "路线暂未推进：当前节点仍有待完成的错题巩固。",
            "先完成当前节点的错题巩固，再进行掌握验证。",
        ),
        "CORE_KNOWLEDGE_EVIDENCE_INSUFFICIENT": (
            "路线暂未推进：当前节点仍缺独立掌握检查等正式证据。",
            "完成分阶测验并通过未见过的掌握检查后，路线才会推进。",
        ),
        "CURRENT_NODE_UNAVAILABLE": (
            "当前节点状态正在同步。",
            "请刷新页面后查看最新学习安排。",
        ),
    }
    title, description = messages.get(
        reason,
        ("路线暂未推进：当前节点仍在核验正式学习证据。", "完成当前节点要求后，系统会重新判断路线进度。"),
    )
    return {"reason": reason, "title": title, "description": description}


def recent_profile_changes(
    db: Session, *, learner_id: int, domain_code: str, limit: int = 5
) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(LearningAdjustmentProposal)
            .join(
                LearningPath,
                LearningPath.id == LearningAdjustmentProposal.resulting_learning_path_id,
            )
            .where(
                LearningAdjustmentProposal.learner_id == learner_id,
                LearningAdjustmentProposal.status.in_(
                    {
                        "resource_pending",
                        "resource_started",
                        "resource_skipped",
                        "evidence_recorded",
                    }
                ),
                LearningPath.domain_code == domain_code,
            )
            .order_by(LearningAdjustmentProposal.updated_at.desc(), LearningAdjustmentProposal.id.desc())
            .limit(limit)
        )
    )
    changes: list[dict[str, Any]] = []
    for item in rows:
        validation = dict(item.validation_result_json or {})
        summary = validation.get("profile_change_summary")
        if not isinstance(summary, dict):
            continue
        changes.append(
            {
                "proposal_id": item.public_id,
                "hypothesis_type": item.hypothesis_type,
                "decision": validation.get("decision"),
                "status": item.status,
                "resource_decision": item.resource_decision,
                "generation_task": (
                    {
                        "task_id": task.public_id,
                        "status": task.status,
                        "decision": task.decision,
                        "failure_reason": task.failure_reason or None,
                    }
                    if (task := db.get(GenerationTask, item.generation_task_id)) is not None
                    else None
                ),
                "profile_change_summary": summary,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
        )
    return changes
