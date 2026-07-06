from fastapi import APIRouter

from app.schemas.common import ApiResponse, ok

router = APIRouter()


@router.get("/demo-accounts", response_model=ApiResponse)
def list_demo_accounts() -> ApiResponse:
    return ok(
        [
            {"user_id": "demo_learner", "role": "learner", "display_name": "学习者演示账号"},
            {"user_id": "demo_instructor", "role": "instructor", "display_name": "培训者演示账号"},
            {"user_id": "demo_admin", "role": "admin", "display_name": "管理员演示账号"},
        ]
    )
