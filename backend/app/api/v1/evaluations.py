from fastapi import APIRouter

from app.schemas.common import ApiResponse, ok

router = APIRouter()


@router.get("/summary", response_model=ApiResponse)
def get_evaluation_summary() -> ApiResponse:
    return ok(
        {
            "case_count": 0,
            "mvp_target_case_count": 50,
            "hallucination_rate": None,
            "difficulty_match_accuracy": None,
            "knowledge_coverage": None,
            "last_run_at": None,
        }
    )
