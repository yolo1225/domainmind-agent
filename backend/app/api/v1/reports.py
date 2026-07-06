from fastapi import APIRouter

from app.schemas.common import ApiResponse, ok

router = APIRouter()


@router.get("/learners/{learner_id}", response_model=ApiResponse)
def get_learning_report(learner_id: str) -> ApiResponse:
    return ok(
        {
            "learner_id": learner_id,
            "radar": [62, 58, 64, 52, 70],
            "path": ["prompt_basic", "embedding_basic", "rag_chunking", "agent_state"],
            "metrics": {
                "difficulty_match": 0.87,
                "knowledge_coverage": 0.91,
                "hallucination_rate": 0.03,
            },
        }
    )
