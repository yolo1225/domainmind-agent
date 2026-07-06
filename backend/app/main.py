from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import DomainError
from app.core.errors import domain_error_handler
from app.core.errors import http_exception_handler
from app.core.errors import validation_exception_handler


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.schema_version,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin, "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(DomainError, domain_error_handler)

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
