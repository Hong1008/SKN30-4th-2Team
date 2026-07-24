"""WorkShield FastAPI 애플리케이션 팩토리."""

from collections.abc import Callable
from typing import AsyncContextManager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router as api_router
from app.common.exception_handlers import register_exception_handlers
from app.common.request_id import register_request_id_middleware
from app.config import get_settings
from app.lifespan import lifespan


LifespanHandler = Callable[[FastAPI], AsyncContextManager[None]]


def create_app(lifespan_handler: LifespanHandler = lifespan) -> FastAPI:
    """설정과 공통 HTTP 계약을 적용한 FastAPI 애플리케이션을 만든다."""
    settings = get_settings()
    app = FastAPI(
        title="WorkShield API",
        version="0.1.0",
        lifespan=lifespan_handler,
    )

    register_request_id_middleware(app)
    register_exception_handlers(app)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "X-Request-ID",
            ],
        )

    app.include_router(api_router)
    return app
