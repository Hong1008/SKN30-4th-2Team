"""공통 API 성공·오류 응답과 안전한 요청 로그 계약을 검증한다."""

import logging
from typing import Annotated

import httpx
import pytest
from fastapi import Body, FastAPI, Request
from pydantic import BaseModel

from app.core.common.errors import NotFoundError
from app.core.common.exception_handlers import register_exception_handlers
from app.core.common.request_id import register_request_id_middleware
from app.core.common.responses import success_response


pytestmark = pytest.mark.asyncio


class SampleRequest(BaseModel):
    """요청 검증 오류 응답을 확인하기 위한 테스트 DTO."""

    count: int


def create_contract_test_app() -> FastAPI:
    """공통 계약만 독립적으로 검증하는 최소 FastAPI 앱을 만든다."""
    test_app = FastAPI()
    register_request_id_middleware(test_app)
    register_exception_handlers(test_app)

    @test_app.get("/success")
    async def success(request: Request):
        return success_response(request, {"value": "ok"})

    @test_app.get("/not-found")
    async def not_found() -> None:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="검토 세션을 찾을 수 없습니다.",
            next_action="START_NEW_REVIEW",
        )

    @test_app.post("/validation")
    async def validation(
        payload: Annotated[SampleRequest, Body()],
    ) -> SampleRequest:
        return payload

    @test_app.get("/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("외부에 노출되면 안 되는 내부 오류")

    return test_app


async def test_success_response_contains_request_metadata() -> None:
    transport = httpx.ASGITransport(app=create_contract_test_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/success")
    body = response.json()

    assert response.status_code == 200
    assert body["data"] == {"value": "ok"}
    assert body["meta"]["request_id"].startswith("req_")
    assert body["meta"]["timestamp"].endswith("Z")
    assert response.headers["X-Request-ID"] == body["meta"]["request_id"]


async def test_request_log_contains_only_safe_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    transport = httpx.ASGITransport(app=create_contract_test_app())

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/success?contract=sensitive-body")

    request_id = response.headers["X-Request-ID"]
    message = next(
        record.getMessage()
        for record in caplog.records
        if "event=http.request.completed" in record.getMessage()
    )
    assert f"request_id={request_id}" in message
    assert "state=200" in message
    assert "duration_ms=" in message
    assert "sensitive-body" not in message
    assert "/success" not in message


async def test_domain_error_uses_common_error_response() -> None:
    transport = httpx.ASGITransport(app=create_contract_test_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/not-found")
    body = response.json()

    assert response.status_code == 404
    assert body["error"] == {
        "code": "SESSION_NOT_FOUND",
        "message": "검토 세션을 찾을 수 없습니다.",
        "field": None,
        "retryable": False,
        "next_action": "START_NEW_REVIEW",
        "details": {},
    }
    assert response.headers["X-Request-ID"] == body["meta"]["request_id"]


async def test_validation_error_does_not_echo_request_body() -> None:
    transport = httpx.ASGITransport(app=create_contract_test_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/validation",
            json={"count": "sensitive-input"},
        )
    body = response.json()

    assert response.status_code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["field"] == "count"
    assert body["error"]["details"] == {"reason": "int_parsing"}
    assert "sensitive-input" not in response.text


async def test_unknown_route_uses_common_error_response() -> None:
    transport = httpx.ASGITransport(app=create_contract_test_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/missing-route")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_unexpected_error_hides_internal_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="uvicorn.error")
    transport = httpx.ASGITransport(app=create_contract_test_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/unexpected")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "외부에 노출되면 안 되는 내부 오류" not in response.text
    assert "외부에 노출되면 안 되는 내부 오류" not in caplog.text
    assert "event=api.unexpected_error" in caplog.text
