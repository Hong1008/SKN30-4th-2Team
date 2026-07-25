"""시스템 상태 확인 API가 실제 애플리케이션 의존성을 검사하는지 검증한다."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.api.system import router as system_router
from app.core.common.exception_handlers import register_exception_handlers
from app.core.common.request_id import register_request_id_middleware
from app.core.db.database import Database
from app.core.llm.mcp.types import WorkShieldMCPRuntime


pytestmark = pytest.mark.asyncio


def create_system_test_app(
    database: Database,
    *,
    include_mcp: bool = True,
) -> FastAPI:
    """lifespan 없이 상태 확인 의존성만 준비한 테스트 앱을 만든다."""
    test_app = FastAPI()
    test_app.state.database = database
    if include_mcp:
        test_app.state.workshield_mcp = WorkShieldMCPRuntime(
            client=SimpleNamespace(),
            session=SimpleNamespace(),
            tools=(),
            capabilities={"status": "OK"},
            supports_file_path=True,
        )
    register_request_id_middleware(test_app)
    register_exception_handlers(test_app)
    test_app.include_router(system_router)
    return test_app


async def test_readiness_checks_database_and_mcp(database: Database) -> None:
    transport = httpx.ASGITransport(app=create_system_test_app(database))

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "mcp": "ok",
    }


async def test_readiness_returns_503_when_database_is_unavailable(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database, "is_ready", lambda: False)
    transport = httpx.ASGITransport(app=create_system_test_app(database))

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


async def test_readiness_returns_503_before_mcp_initialization(
    database: Database,
) -> None:
    transport = httpx.ASGITransport(
        app=create_system_test_app(database, include_mcp=False),
    )

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
