from fastapi import APIRouter

from app.schemas.common import ApiResponse, ok

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_learners() -> ApiResponse:
    return ok(
        [
            {
                "learner_id": "learner_001",
                "profile_type": "beginner",
                "target_domain": "ai_app_dev",
                "ability_level": 2,
            },
            {
                "learner_id": "learner_002",
                "profile_type": "advanced",
                "target_domain": "ai_app_dev",
                "ability_level": 4,
            },
            {
                "learner_id": "learner_003",
                "profile_type": "practice_oriented",
                "target_domain": "ai_app_dev",
                "ability_level": 3,
            },
        ]
    )


@router.get("/{learner_id}/profile", response_model=ApiResponse)
def get_learner_profile(learner_id: str) -> ApiResponse:
    return ok(
        {
            "learner_id": learner_id,
            "domain_code": "ai_app_dev",
            "learning_style": "mixed",
            "ability_profile": {
                "theory": 62,
                "practice": 58,
                "problem_solving": 64,
                "breadth": 52,
                "learning_speed": 70,
            },
            "weak_knowledge": [
                {"knowledge_id": "rag_chunking", "name": "RAG 切片策略", "weakness_level": 4},
                {"knowledge_id": "agent_state", "name": "Agent 状态设计", "weakness_level": 3},
            ],
        }
    )
