from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AnswerRecord,
    DiagnosticQuestion,
    KnowledgeItem,
    KnowledgeRelation,
    Learner,
    LearnerProfile,
    LearningPath,
)

RADAR_KEYS = ["theory", "practice", "problem_solving", "breadth", "learning_speed"]
RESOURCE_TYPES = ["lecture", "practice_guide", "graded_quiz"]
MOJIBAKE_MARKERS = ("Ã", "Â", "å", "æ", "ç", "è", "é", "ð", "\x80", "\x81")


def public_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def clean_display_text(value: str) -> str:
    if not value or not any(marker in value for marker in MOJIBAKE_MARKERS):
        return value
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value
    return repaired if repaired else value


def clean_display_payload(value: Any) -> Any:
    if isinstance(value, str):
        return clean_display_text(value)
    if isinstance(value, list):
        return [clean_display_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            clean_display_text(key) if isinstance(key, str) else key: clean_display_payload(item)
            for key, item in value.items()
        }
    return value


def classify_profile_level(score: float) -> str:
    if score < 60:
        return "beginner"
    if score < 85:
        return "intermediate"
    return "advanced"


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


def _bounded(value: float, low: int = 20, high: int = 95) -> int:
    return max(low, min(high, round(value)))


def _category_value(category_scores: dict[str, list[float]], keywords: tuple[str, ...], fallback: float) -> float:
    values: list[float] = []
    for category, scores in category_scores.items():
        if any(keyword.lower() in category.lower() for keyword in keywords):
            values.extend(scores)
    if not values:
        return fallback
    return sum(values) / len(values) * 100


def build_ability_profile(
    score_percent: float,
    category_scores: dict[str, list[float]],
    *,
    average_difficulty: float,
    profile_type: str | None = None,
) -> dict[str, Any]:
    base_type = profile_type or classify_profile_level(score_percent)
    category_mastery = {
        category: round(sum(scores) / len(scores) * 100, 1)
        for category, scores in sorted(category_scores.items())
        if scores
    }

    theory = _category_value(category_scores, ("理论", "基础", "prompt", "embedding"), score_percent)
    practice = _category_value(category_scores, ("实操", "实践", "应用", "rag", "agent"), score_percent - 4)
    problem_solving = _bounded((score_percent * 0.7) + (average_difficulty * 8))
    breadth = _bounded((sum(category_mastery.values()) / max(1, len(category_mastery))) - 6)
    learning_speed = _bounded(score_percent + 4)

    ability = {
        "profile_type": base_type,
        "theory": _bounded(theory),
        "practice": _bounded(practice),
        "problem_solving": problem_solving,
        "breadth": breadth,
        "learning_speed": learning_speed,
        "category_mastery": category_mastery,
    }
    if ability["practice"] >= ability["theory"] + 10 and score_percent >= 60:
        ability["profile_type"] = "practice_oriented"
    return ability


def _weakness_type(avg_score: float) -> str:
    if avg_score < 0.2:
        return "not_mastered"
    if avg_score < 0.6:
        return "partial_confusion"
    return "needs_consolidation"


def _relation_public_ids(
    db: Session,
    knowledge_item_ids: list[int],
    relation_type: str,
) -> dict[int, list[str]]:
    if not knowledge_item_ids:
        return {}
    rows = db.execute(
        select(KnowledgeRelation.source_item_id, KnowledgeItem.public_id)
        .join(KnowledgeItem, KnowledgeItem.id == KnowledgeRelation.target_item_id)
        .where(KnowledgeRelation.source_item_id.in_(knowledge_item_ids))
        .where(KnowledgeRelation.relation_type == relation_type)
    ).all()
    grouped: dict[int, list[str]] = defaultdict(list)
    for source_item_id, target_public_id in rows:
        grouped[source_item_id].append(target_public_id)
    return dict(grouped)


def build_weak_knowledge(
    db: Session,
    weak_evidence: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not weak_evidence:
        return []
    item_ids = list(weak_evidence.keys())
    items = {
        item.id: item
        for item in db.scalars(select(KnowledgeItem).where(KnowledgeItem.id.in_(item_ids)))
    }
    prerequisites = _relation_public_ids(db, item_ids, "prerequisite")

    weak_items: list[dict[str, Any]] = []
    for item_id, evidence in weak_evidence.items():
        item = items.get(item_id)
        if item is None:
            continue
        attempts = max(1, evidence["attempts"])
        avg_score = evidence["score_total"] / attempts
        wrong_count = evidence["wrong_count"]
        difficulty = evidence["difficulty_total"] / attempts
        weakness_level = min(5, max(1, round((1 - avg_score) * 3 + wrong_count + difficulty / 2)))
        weak_items.append(
            {
                "knowledge_id": item.public_id,
                "name": clean_display_text(item.name),
                "category": clean_display_text(item.category),
                "weakness_level": weakness_level,
                "weakness_type": _weakness_type(avg_score),
                "suggested_action": "补救讲解" if weakness_level >= 4 else "巩固练习",
                "evidence": {
                    "wrong_count": wrong_count,
                    "attempts": attempts,
                    "avg_score": round(avg_score, 2),
                },
                "prerequisites": prerequisites.get(item_id, []),
            }
        )

    weak_items.sort(key=lambda item: (-item["weakness_level"], item["name"]))
    return weak_items


def build_learning_path_payload(
    *,
    profile_type: str,
    score_percent: float,
    weak_knowledge: list[dict[str, Any]],
) -> dict[str, Any]:
    prerequisite_ids: list[str] = []
    for item in weak_knowledge:
        for prerequisite in item.get("prerequisites", []):
            if prerequisite not in prerequisite_ids:
                prerequisite_ids.append(prerequisite)

    priority_ids = [item["knowledge_id"] for item in weak_knowledge[:5]]
    stages = []
    if prerequisite_ids:
        stages.append(
            {
                "name": "补齐前置知识",
                "description": "先补足薄弱知识点依赖的基础概念。",
                "knowledge_ids": prerequisite_ids[:5],
            }
        )
    stages.append(
        {
            "name": "攻克薄弱知识点",
            "description": "围绕诊断错题和低分题对应知识点集中练习。",
            "knowledge_ids": priority_ids,
        }
    )
    stages.append(
        {
            "name": "生成个性化资源",
            "description": "生成讲义、实操指南和分阶测试题。",
            "resource_types": RESOURCE_TYPES,
        }
    )
    stages.append(
        {
            "name": "反馈后更新画像",
            "description": "根据太难、太简单、有错误等反馈调整学习路径。",
            "trigger": "resource_feedback",
        }
    )
    return {
        "profile_type": profile_type,
        "score": score_percent,
        "stages": stages,
    }


def generate_profile_from_diagnostic(
    db: Session,
    *,
    learner: Learner,
    domain_code: str,
    session_id: str,
    questions: list[DiagnosticQuestion],
    answer_by_question_id: dict[str, Any],
) -> dict[str, Any]:
    knowledge_item_ids = [question.knowledge_item_id for question in questions]
    knowledge_items = {
        item.id: item
        for item in db.scalars(select(KnowledgeItem).where(KnowledgeItem.id.in_(knowledge_item_ids)))
    }

    total_score = 0.0
    correct_count = 0
    category_scores: dict[str, list[float]] = defaultdict(list)
    weak_evidence: dict[int, dict[str, Any]] = {}
    difficulty_total = 0

    for question in questions:
        answer = answer_by_question_id.get(question.public_id)
        score, is_correct = score_answer(question, answer)
        item = knowledge_items[question.knowledge_item_id]
        total_score += score
        correct_count += 1 if is_correct else 0
        difficulty_total += question.difficulty
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
                    "score": round(score, 2),
                },
            )
        )
        if (not is_correct) or score < 0.6:
            evidence = weak_evidence.setdefault(
                item.id,
                {
                    "wrong_count": 0,
                    "attempts": 0,
                    "score_total": 0.0,
                    "difficulty_total": 0.0,
                },
            )
            evidence["wrong_count"] += 0 if is_correct else 1
            evidence["attempts"] += 1
            evidence["score_total"] += score
            evidence["difficulty_total"] += question.difficulty

    question_count = max(1, len(questions))
    score_percent = round(total_score / question_count * 100, 1)
    average_difficulty = difficulty_total / question_count
    ability_profile = build_ability_profile(
        score_percent,
        category_scores,
        average_difficulty=average_difficulty,
    )
    ability_profile = clean_display_payload(ability_profile)
    weak_knowledge = build_weak_knowledge(db, weak_evidence)
    learning_path_payload = build_learning_path_payload(
        profile_type=ability_profile["profile_type"],
        score_percent=score_percent,
        weak_knowledge=weak_knowledge,
    )

    profile = LearnerProfile(
        public_id=public_id("profile"),
        learner_id=learner.id,
        domain_code=domain_code,
        ability_profile_json=ability_profile,
        weak_knowledge_json=weak_knowledge[:8],
    )
    db.add(profile)
    db.flush()

    path = LearningPath(
        public_id=public_id("path"),
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code=domain_code,
        status="active",
        path_json=learning_path_payload,
        needs_refresh=False,
    )
    db.add(path)
    db.flush()

    return {
        "session_id": session_id,
        "learner_id": learner.public_id,
        "status": "scored",
        "score": score_percent,
        "correct_count": correct_count,
        "question_count": len(questions),
        "profile_id": profile.public_id,
        "profile_type": ability_profile["profile_type"],
        "ability_profile": ability_profile,
        "weak_knowledge": weak_knowledge[:8],
        "learning_path_id": path.public_id,
        "learning_path": learning_path_payload,
        "next_action": "create_generation_task",
    }


def latest_profile_for_learner(db: Session, learner: Learner) -> LearnerProfile | None:
    return db.scalar(
        select(LearnerProfile)
        .where(LearnerProfile.learner_id == learner.id)
        .order_by(LearnerProfile.id.desc())
    )


def latest_path_for_profile(db: Session, profile: LearnerProfile) -> LearningPath | None:
    return db.scalar(
        select(LearningPath)
        .where(LearningPath.profile_id == profile.id)
        .order_by(LearningPath.id.desc())
    )


def default_profile_for_learner(db: Session, learner: Learner) -> LearnerProfile:
    profile = latest_profile_for_learner(db, learner)
    if profile is not None:
        return profile
    profile = LearnerProfile(
        public_id=public_id("profile"),
        learner_id=learner.id,
        domain_code=learner.target_domain,
        ability_profile_json=build_ability_profile(
            55,
            defaultdict(list),
            average_difficulty=2,
            profile_type="beginner",
        ),
        weak_knowledge_json=[],
    )
    db.add(profile)
    db.flush()
    return profile


def radar_values(ability_profile: dict[str, Any] | None) -> list[int]:
    ability_profile = ability_profile or {}
    return [int(ability_profile.get(key, 0) or 0) for key in RADAR_KEYS]


def profile_ability_level(ability_profile: dict[str, Any] | None) -> int:
    values = radar_values(ability_profile)
    average = sum(values) / max(1, len(values))
    return max(1, min(5, round(average / 20)))


def diagnostic_summary_for_learner(db: Session, learner: Learner) -> dict[str, Any]:
    total_count = db.scalar(
        select(func.count(AnswerRecord.id)).where(AnswerRecord.learner_id == learner.id)
    ) or 0
    correct_count = db.scalar(
        select(func.count(AnswerRecord.id))
        .where(AnswerRecord.learner_id == learner.id)
        .where(AnswerRecord.is_correct.is_(True))
    ) or 0
    latest_answer = db.scalar(
        select(AnswerRecord)
        .where(AnswerRecord.learner_id == learner.id)
        .order_by(AnswerRecord.id.desc())
    )
    return {
        "answer_count": total_count,
        "correct_count": correct_count,
        "accuracy": round(correct_count / total_count * 100, 1) if total_count else 0,
        "latest_session_id": (latest_answer.answer_summary_json or {}).get("session_id")
        if latest_answer
        else None,
    }


def serialize_profile_detail(
    db: Session,
    learner: Learner,
    profile: LearnerProfile | None = None,
) -> dict[str, Any]:
    profile = profile or latest_profile_for_learner(db, learner)
    if profile is None:
        return {
            "learner_id": learner.public_id,
            "domain_code": learner.target_domain,
            "background": clean_display_text(learner.background),
            "learning_style": learner.learning_style,
            "experience_years": learner.experience_years,
            "profile_status": "not_started",
            "profile_id": None,
            "profile_type": "not_started",
            "ability_profile": {},
            "radar": [0, 0, 0, 0, 0],
            "category_mastery": {},
            "weak_knowledge": [],
            "learning_path": None,
            "diagnostic_summary": diagnostic_summary_for_learner(db, learner),
        }

    ability_profile = profile.ability_profile_json or {}
    path = latest_path_for_profile(db, profile)
    return {
        "learner_id": learner.public_id,
        "domain_code": profile.domain_code,
        "background": clean_display_text(learner.background),
        "learning_style": learner.learning_style,
        "experience_years": learner.experience_years,
        "profile_status": "ready",
        "profile_id": profile.public_id,
        "profile_type": ability_profile.get("profile_type", "beginner"),
        "ability_profile": clean_display_payload(ability_profile),
        "radar": radar_values(ability_profile),
        "category_mastery": clean_display_payload(ability_profile.get("category_mastery", {})),
        "weak_knowledge": clean_display_payload(profile.weak_knowledge_json or []),
        "learning_path": clean_display_payload(path.path_json) if path else None,
        "diagnostic_summary": diagnostic_summary_for_learner(db, learner),
    }
