from fastapi import APIRouter

from app.core.db import check_database_connection
from app.rag.vector_store import get_vector_store
from app.schemas.common import ApiResponse, ok

router = APIRouter()


@router.get("/health", response_model=ApiResponse)
def health_check() -> ApiResponse:
    return ok({"status": "ok", "service": "backend", "api_prefix": "/api/v1"})


@router.get("/health/dependencies", response_model=ApiResponse)
def dependency_health_check() -> ApiResponse:
    database = _check_dependency("database", check_database_connection)
    chroma = _check_dependency("chroma", get_vector_store().health_check)
    overall_status = "ok" if database["status"] == chroma["status"] == "ok" else "degraded"
    return ok({"status": overall_status, "database": database, "chroma": chroma})


def _check_dependency(name: str, checker) -> dict:
    try:
        return checker()
    except Exception as exc:
        return {"status": "degraded", "dependency": name, "error": str(exc)}
