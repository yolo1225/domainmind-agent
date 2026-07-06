from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.graphs import build_generation_graph
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
    LearningPath,
    LearningResource,
    ReviewReport,
)


RESOURCE_TYPES = ["lecture", "practice_guide", "graded_quiz"]


def public_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def get_or_create_demo_learner(db: Session, learner_public_id: str = "learner_001") -> Learner:
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_public_id))
    if learner is None:
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


def question_payload(question: DiagnosticQuestion) -> dict[str, Any]:
    return {
        "question_id": question.public_id,
        "knowledge_id": question.knowledge_item_id,
        "question_type": question.question_type,
        "stem": question.stem,
        "options": question.options_json or [],
        "difficulty": question.difficulty,
    }


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
        "questions": [question_payload(question) for question in questions],
    }


def score_answer(question: DiagnosticQuestion, answer: Any) -> tuple[float, bool]:
    answer_key = question.answer_key_json or {}
    if question.question_type == "single_choice":
        expected = answer_key.get("correct_option")
        try:
            selected = int(answer)
        except (TypeError, ValueError):
            selected = -1
        is_correct = selected == expected
        return (1.0 if is_correct else 0.0), is_correct

    answer_text = str(answer or "")
    rubric = answer_key.get("rubric", [])
    if not rubric:
        return (0.0, False)
    matched = sum(1 for item in rubric if str(item) in answer_text)
    score = matched / len(rubric)
    return score, score >= 0.6


def classify_profile(score_percent: float) -> str:
    if score_percent >= 80:
        return "advanced"
    if score_percent >= 60:
        return "intermediate"
    return "beginner"


def build_ability_profile(score_percent: float, profile_type: str) -> dict[str, Any]:
    base = max(20, min(90, int(score_percent)))
    return {
        "profile_type": profile_type,
        "theory": base,
        "practice": max(20, min(90, base - 8)),
        "problem_solving": max(20, min(90, base - 4)),
        "breadth": max(20, min(90, base - 10)),
        "learning_speed": max(20, min(90, base + 5)),
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
    questions = list(
        db.scalars(
            select(DiagnosticQuestion).where(
                DiagnosticQuestion.public_id.in_(answer_by_question_id.keys())
            )
        )
    )
    knowledge_items = {
        item.id: item
        for item in db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.id.in_([question.knowledge_item_id for question in questions])
            )
        )
    }

    total_score = 0.0
    weak_items: list[dict[str, Any]] = []
    category_scores: dict[str, list[float]] = defaultdict(list)

    for question in questions:
        answer = answer_by_question_id[question.public_id]
        score, is_correct = score_answer(question, answer)
        total_score += score
        item = knowledge_items[question.knowledge_item_id]
        category_scores[item.category].append(score)
        db.add(
            AnswerRecord(
                learner_id=learner.id,
                question_id=question.id,
                knowledge_item_id=item.id,
                score=score,
                is_correct=is_correct,
                answer_summary_json={
                    "session_id": session_id,
                    "question_id": question.public_id,
                    "answer_type": question.question_type,
                },
            )
        )
        if not is_correct:
            weak_items.append(
                {
                    "knowledge_id": item.public_id,
                    "name": item.name,
                    "category": item.category,
                    "weakness_level": max(1, min(5, question.difficulty + 1)),
                }
            )

    question_count = max(1, len(questions))
    score_percent = round(total_score / question_count * 100, 1)
    profile_type = classify_profile(score_percent)
    ability_profile = build_ability_profile(score_percent, profile_type)
    ability_profile["category_mastery"] = {
        category: round(sum(scores) / len(scores) * 100, 1)
        for category, scores in category_scores.items()
    }

    if not weak_items:
        weak_items = [
            {
                "knowledge_id": "learning_path_generation",
                "name": "学习路径生成",
                "category": "个性化学习",
                "weakness_level": 2,
            }
        ]

    profile = LearnerProfile(
        public_id=public_id("profile"),
        learner_id=learner.id,
        domain_code=domain_code,
        ability_profile_json=ability_profile,
        weak_knowledge_json=weak_items[:5],
    )
    db.add(profile)
    db.flush()

    path = LearningPath(
        public_id=public_id("path"),
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code=domain_code,
        status="active",
        path_json={
            "profile_type": profile_type,
            "score": score_percent,
            "stages": [
                {
                    "name": "补齐薄弱知识",
                    "knowledge_ids": [item["knowledge_id"] for item in weak_items[:3]],
                },
                {"name": "生成个性化资源", "resource_types": RESOURCE_TYPES},
                {"name": "反馈后更新路径", "trigger": "resource_feedback"},
            ],
        },
        needs_refresh=False,
    )
    db.add(path)
    db.commit()

    return {
        "session_id": session_id,
        "learner_id": learner.public_id,
        "status": "scored",
        "score": score_percent,
        "correct_count": sum(1 for question in questions if score_answer(question, answer_by_question_id[question.public_id])[1]),
        "question_count": len(questions),
        "profile_id": profile.public_id,
        "profile_type": profile_type,
        "ability_profile": ability_profile,
        "weak_knowledge": weak_items[:5],
        "learning_path_id": path.public_id,
        "next_action": "create_generation_task",
    }


def latest_profile_for_learner(db: Session, learner: Learner) -> LearnerProfile:
    profile = db.scalar(
        select(LearnerProfile)
        .where(LearnerProfile.learner_id == learner.id)
        .order_by(LearnerProfile.id.desc())
    )
    if profile is None:
        profile = LearnerProfile(
            public_id=public_id("profile"),
            learner_id=learner.id,
            domain_code=learner.target_domain,
            ability_profile_json=build_ability_profile(55, "beginner"),
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
    return profile


def create_generation_task(
    db: Session,
    *,
    learner_id: str = "learner_001",
    profile_id: str | None = None,
    domain_code: str = "ai_app_dev",
    resource_types: list[str] | None = None,
) -> dict[str, Any]:
    learner = get_or_create_demo_learner(db, learner_id)
    profile = (
        db.scalar(select(LearnerProfile).where(LearnerProfile.public_id == profile_id))
        if profile_id
        else latest_profile_for_learner(db, learner)
    )
    if profile is None:
        profile = latest_profile_for_learner(db, learner)

    requested_types = resource_types or RESOURCE_TYPES
    task = GenerationTask(
        public_id=public_id("task"),
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code=domain_code,
        status="completed",
        resource_types_json=requested_types,
        revision_count=0,
        decision="passed",
    )
    db.add(task)
    db.flush()

    graph = build_generation_graph()
    graph_result = graph.invoke(
        {
            "task_id": task.public_id,
            "learner_id": learner.public_id,
            "profile_id": profile.public_id,
            "domain_code": domain_code,
            "resource_types": requested_types,
            "learning_goal": "根据诊断结果生成个性化学习资源",
            "profile": {
                **(profile.ability_profile_json or {}),
                "weak_knowledge": profile.weak_knowledge_json or [],
            },
            "retrieved_chunks": [],
            "draft_resources": [],
            "review_reports": [],
            "revision_count": 0,
            "decision": "pending",
            "error_message": None,
            "agent_trace": [],
        }
    )
    task.decision = graph_result.get("decision", "failed")
    task.status = "completed" if task.decision == "passed" else "failed"
    task.revision_count = graph_result.get("revision_count", 0)

    resources: list[LearningResource] = []
    for draft in graph_result.get("draft_resources", []):
        resource = LearningResource(
            public_id=public_id("res"),
            generation_task_id=task.id,
            resource_type=draft["resource_type"],
            title=draft["title"],
            content_md=draft["content"],
            difficulty=draft["difficulty"],
            learner_profile_type=profile.ability_profile_json.get("profile_type", ""),
            sources_json=draft["sources"],
            version=1,
            review_status="passed" if task.decision == "passed" else "failed",
        )
        db.add(resource)
        db.flush()
        report = next(
            (
                item
                for item in graph_result.get("review_reports", [])
                if item.get("resource_type") == resource.resource_type
            ),
            {},
        )
        db.add(
            ReviewReport(
                resource_id=resource.id,
                primary_review_json={
                    "score": report.get("facts_score", 0),
                    "factual_accuracy": report.get("facts_score", 0),
                    "source_traceability": report.get("source_traceability_score", 0),
                    "difficulty_match": report.get("difficulty_match_score", 0),
                },
                secondary_review_json={
                    "score": report.get("coverage_score", 0),
                    "factual_accuracy": report.get("facts_score", 0),
                    "source_traceability": report.get("source_traceability_score", 0),
                    "difficulty_match": report.get("difficulty_match_score", 0),
                },
                arbitration_json={"required": False, "reason": "score_gap_within_10"},
                manual_review_required=False,
                passed=bool(report.get("passed")),
            )
        )
        resources.append(resource)

    for trace in graph_result.get("agent_trace", []):
        db.add(
            AgentRun(
                generation_task_id=task.id,
                agent_name=trace["agent_name"],
                status=trace["status"],
                input_summary_json={"task_id": task.public_id},
                output_summary_json=trace["output"],
                llm_calls=0,
                tokens_used=0,
                duration_ms=20,
            )
        )
        db.add(
            AgentMessageRecord(
                session_id=task.public_id,
                task_id=task.public_id,
                sender=trace["agent_name"],
                receiver="orchestrator_agent",
                message_type="status",
                payload_summary_json=trace["output"],
            )
        )

    db.commit()
    return {
        "task_id": task.public_id,
        "status": task.status,
        "resource_types": requested_types,
        "agent_graph": "rule_based_mvp_graph",
        "decision": task.decision,
        "agent_trace": graph_result.get("agent_trace", []),
        "resources": [serialize_resource(resource) for resource in resources],
    }


def serialize_resource(resource: LearningResource) -> dict[str, Any]:
    return {
        "resource_id": resource.public_id,
        "resource_type": resource.resource_type,
        "title": resource.title,
        "content": resource.content_md,
        "difficulty": resource.difficulty,
        "learner_profile_type": resource.learner_profile_type,
        "review_status": resource.review_status,
        "sources": [item.get("knowledge_id") for item in (resource.sources_json or [])],
        "source_details": resource.sources_json or [],
        "version": resource.version,
    }


def list_resources(db: Session) -> list[dict[str, Any]]:
    resources = list(
        db.scalars(select(LearningResource).order_by(LearningResource.id.desc()).limit(30))
    )
    return [serialize_resource(resource) for resource in resources]


def submit_feedback(
    db: Session,
    *,
    resource_id: str,
    learner_id: str = "learner_001",
    feedback_type: str = "confusing",
    rating: int = 3,
    comment: str = "",
) -> dict[str, Any]:
    learner = get_or_create_demo_learner(db, learner_id)
    resource = db.scalar(select(LearningResource).where(LearningResource.public_id == resource_id))
    if resource is None:
        raise ValueError(f"Resource not found: {resource_id}")

    action = {
        "too_easy": "challenge_task",
        "too_hard": "remedial_explanation",
        "incorrect": "revision_required",
        "confusing": "remedial_explanation",
    }.get(feedback_type, "profile_update")
    feedback = Feedback(
        resource_id=resource.id,
        learner_id=learner.id,
        rating=rating,
        feedback_type=feedback_type,
        feedback_summary_json={
            "comment_summary": comment[:120],
            "resource_type": resource.resource_type,
        },
        triggered_action=action,
    )
    db.add(feedback)

    profile = latest_profile_for_learner(db, learner)
    ability_profile = dict(profile.ability_profile_json or {})
    if feedback_type in {"too_hard", "confusing"}:
        ability_profile["practice"] = max(20, int(ability_profile.get("practice", 50)) - 3)
    elif feedback_type == "too_easy":
        ability_profile["problem_solving"] = min(95, int(ability_profile.get("problem_solving", 50)) + 3)
    ability_profile["last_feedback_action"] = action
    profile.ability_profile_json = ability_profile

    path = db.scalar(
        select(LearningPath)
        .where(LearningPath.learner_id == learner.id)
        .order_by(LearningPath.id.desc())
    )
    if path is not None:
        path.needs_refresh = True
        path.path_json = {
            **(path.path_json or {}),
            "last_feedback_action": action,
            "feedback_resource_id": resource.public_id,
        }

    db.commit()
    return {
        "resource_id": resource.public_id,
        "feedback_status": "accepted",
        "triggered_agent": "tutoring_agent",
        "triggered_action": action,
        "profile_id": profile.public_id,
        "learning_path_needs_refresh": True,
    }
