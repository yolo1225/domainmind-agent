from fastapi import APIRouter

from app.api.v1 import (
    auth,
    diagnostics,
    domains,
    evaluations,
    generation_tasks,
    health,
    knowledge,
    learners,
    reports,
    resources,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(learners.router, prefix="/learners", tags=["learners"])
api_router.include_router(diagnostics.router, prefix="/diagnostics", tags=["diagnostics"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(generation_tasks.router, prefix="/generation-tasks", tags=["generation-tasks"])
api_router.include_router(resources.router, prefix="/resources", tags=["resources"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(domains.router, prefix="/domains", tags=["domains"])
api_router.include_router(evaluations.router, prefix="/evaluations", tags=["evaluations"])
