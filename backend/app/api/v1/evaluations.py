from typing import Literal

from fastapi import APIRouter, Query

from app.schemas.common import ApiResponse, ok
from app.services.evaluation_service import load_evaluation_summary

router = APIRouter()


@router.get("/summary", response_model=ApiResponse)
def get_evaluation_summary(
    mode: Literal["live", "baseline"] = Query(default="live"),
) -> ApiResponse:
    return ok(load_evaluation_summary(mode))
