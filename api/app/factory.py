"""WorkShield FastAPI 애플리케이션 팩토리."""

from collections.abc import Callable
from typing import AsyncContextManager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.router import router as api_router
from app.core.common.exception_handlers import register_exception_handlers
from app.core.common.request_id import register_request_id_middleware
from app.config import get_settings
from app.lifespan import lifespan


LifespanHandler = Callable[[FastAPI], AsyncContextManager[None]]


API_DESCRIPTION = """
WorkShield는 업로드한 계약서를 표준계약서와 비교해 검토 후보를 제공하는 API입니다.
응답은 SSE를 제외하고 모두 `{ "data": ..., "meta": ... }` 형식이며, 오류는
`{ "error": { "code", "message", "retryable", "next_action" }, "meta": ... }`
형식입니다.

## 익명 세션 Cookie

세션 생성(`POST /api/v1/review-sessions`)은 `workshield_session` HttpOnly Cookie를
설정합니다. 이후 세션·검토 API는 해당 Cookie의 소유자만 접근할 수 있습니다. 클라이언트는
Cookie 기반 요청에 `credentials: "include"`(Axios는 `withCredentials: true`)를 사용해야 하며,
토큰을 브라우저 저장소나 URL에 저장하지 않습니다.

## 멱등성 요청

`Idempotency-Key`가 명시된 POST API는 이 헤더가 필수입니다(공백 제외 최대 128자).
네트워크 재전송을 포함한 **같은 논리 요청**에는 같은 키를 사용하면 기존 성공 응답을
재생합니다. 새 논리 요청에는 새 키를 사용해야 합니다. 같은 세션·같은 API 작업 범위에서
같은 키를 다른 요청 본문 또는 다른 review에 재사용하면 `409 IDEMPOTENCY_KEY_REUSED`를
반환합니다. 키와 응답 스냅샷은 익명 세션 TTL 동안 보존됩니다.

## 검토 진행 SSE

`GET /api/v1/reviews/{review_id}/events`는 `text/event-stream`으로 진행 상태를 제공합니다.
이벤트 ID는 단조 증가 `sequence`이며, 재연결 시 `Last-Event-ID` 헤더를 보내면 그 이하
sequence는 재전송하지 않습니다. 연결이 끊기거나 SSE를 사용할 수 없으면
`GET /api/v1/reviews/{review_id}`를 폴링해 상태를 복구할 수 있습니다.
""".strip()


def _register_openapi_schema(app: FastAPI) -> None:
    """공통 런타임 규칙을 OpenAPI 스키마에도 반영한다."""

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        for path_item in schema.get("paths", {}).values():
            for operation in path_item.values():
                if not isinstance(operation, dict):
                    continue
                for parameter in operation.get("parameters", []):
                    if (
                        parameter.get("in") == "header"
                        and parameter.get("name") == "Idempotency-Key"
                    ):
                        # 런타임에서는 공통 오류 envelope를 반환하기 위해 optional
                        # Header로 받은 뒤 명시적으로 검증한다. 외부 계약은 필수다.
                        parameter["required"] = True
                        parameter["description"] = (
                            "필수. 같은 논리 요청의 재전송에는 같은 키를 사용하고, "
                            "새 논리 요청에는 새 키를 사용합니다. 최대 128자입니다."
                        )
                        parameter.setdefault("schema", {}).setdefault("maxLength", 128)
        # FastAPI는 ``responses.model``을 JSON 응답으로도 자동 문서화하지만,
        # 이 엔드포인트의 실제 200 응답은 SSE뿐이다.
        event_response = (
            schema.get("paths", {})
            .get("/api/v1/reviews/{review_id}/events", {})
            .get("get", {})
            .get("responses", {})
            .get("200", {})
        )
        event_response.get("content", {}).pop("application/json", None)
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


def create_app(lifespan_handler: LifespanHandler = lifespan) -> FastAPI:
    """설정과 공통 HTTP 계약을 적용한 FastAPI 애플리케이션을 만든다."""
    settings = get_settings()
    app = FastAPI(
        title="WorkShield API",
        version="0.1.0",
        description=API_DESCRIPTION,
        debug=settings.app_debug,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
        lifespan=lifespan_handler,
    )
    _register_openapi_schema(app)

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
