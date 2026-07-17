from datetime import UTC, datetime
from typing import Any

from app.models import LearnerProfile, LearningPath
from app.services.profile_service import build_learning_path_payload


def build_metric_summary(hallucination_rate: float, difficulty_match: float, coverage: float) -> dict:
    return {
        "hallucination_rate": hallucination_rate,
        "difficulty_match": difficulty_match,
        "difficulty_match_accuracy": difficulty_match,
        "knowledge_coverage": coverage,
    }


def refresh_learning_path(
    *,
    path: LearningPath,
    profile: LearnerProfile,
    profile_detail: dict[str, Any],
) -> dict[str, Any]:
    raw_weak = profile_detail.get("weak_knowledge") or []
    weak_knowledge = [
        item
        if isinstance(item, dict)
        else {"knowledge_id": str(item), "name": str(item), "prerequisites": []}
        for item in raw_weak
    ]
    diagnostic = profile_detail.get("diagnostic_summary") or {}
    ability = profile.ability_profile_json or {}
    payload = build_learning_path_payload(
        profile_type=str(
            profile_detail.get("profile_type")
            or ability.get("profile_type")
            or "beginner"
        ),
        score_percent=float(diagnostic.get("score_percent") or 0),
        weak_knowledge=weak_knowledge,
    )
    payload["refresh_reason"] = (path.path_json or {}).get(
        "knowledge_update_reason", "profile_or_knowledge_changed"
    )
    payload["refreshed_at"] = datetime.now(UTC).isoformat()
    path.path_json = payload
    path.profile_id = profile.id
    path.needs_refresh = False
    return payload
