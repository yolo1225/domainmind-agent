from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.compatibility import SCHEMA_VERSION


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    data: Any | None = None
    error: ApiError | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


def ok(data: Any) -> ApiResponse:
    return ApiResponse(data=data)


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> ApiResponse:
    return ApiResponse(error=ApiError(code=code, message=message, details=details))
