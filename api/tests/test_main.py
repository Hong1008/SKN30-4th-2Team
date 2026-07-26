"""FastAPI 애플리케이션 팩토리와 MCP lifespan 연결을 검증한다."""

from contextlib import asynccontextmanager
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.lifespan as lifespan_module
import app.factory as factory_module
from app.config import Settings
from app.core.db.database import Database
from app.factory import create_app
from app.core.llm.mcp.types import WorkShieldMCPRuntime
from app.lifespan import lifespan
from main import app


def test_create_app_registers_common_routes() -> None:
    created_app = create_app()
    route_paths = set(created_app.openapi()["paths"])

    assert created_app.title == "WorkShield API"
    assert "/health/live" in route_paths
    assert "/health/ready" in route_paths


def test_openapi_describes_common_idempotency_and_review_progress_contracts() -> None:
    """구현된 공통 계약과 SSE/업로드의 비표준 응답을 명세에 고정한다."""
    schema = create_app().openapi()

    description = schema["info"]["description"]
    assert "Idempotency-Key" in description
    assert "Last-Event-ID" in description

    start_review = schema["paths"]["/api/v1/reviews"]["post"]
    idempotency_header = next(
        parameter
        for parameter in start_review["parameters"]
        if parameter["name"] == "Idempotency-Key"
    )
    assert idempotency_header["required"] is True
    assert idempotency_header["schema"]["maxLength"] == 128

    upload_responses = schema["paths"]["/api/v1/review-sessions"]["post"][
        "responses"
    ]
    assert {"413", "415", "422"}.issubset(upload_responses)

    event_response = schema["paths"]["/api/v1/reviews/{review_id}/events"][
        "get"
    ]["responses"]["200"]
    assert set(event_response["content"]) == {"text/event-stream"}


def test_production_can_disable_debug_and_openapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        app_env="prod",
        llm_provider="ollama",
        app_debug=False,
        api_docs_enabled=False,
        database_echo=False,
    )
    monkeypatch.setattr(factory_module, "get_settings", lambda: settings)

    created_app = create_app()

    assert created_app.debug is False
    assert created_app.openapi_url is None
    route_paths = {
        route.path
        for route in created_app.routes
        if hasattr(route, "path")
    }
    assert "/docs" not in route_paths
    assert "/redoc" not in route_paths


@pytest.mark.asyncio
async def test_lifespan_exposes_and_cleans_mcp_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = WorkShieldMCPRuntime(
        client=SimpleNamespace(),
        session=SimpleNamespace(),
        tools=(),
        capabilities={"status": "OK"},
        supports_file_path=True,
    )
    closed = False

    @asynccontextmanager
    async def fake_open(settings):
        nonlocal closed
        try:
            yield runtime
        finally:
            closed = True

    database_path = tmp_path / "lifespan.db"
    settings = SimpleNamespace(
        database_url=f"sqlite+pysqlite:///{database_path}",
        database_echo=False,
        temp_upload_dir=tmp_path / "uploads",
        storage_cleanup_interval_seconds=60,
    )
    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    monkeypatch.setattr(lifespan_module, "open_workshield_mcp", fake_open)

    async with lifespan(app):
        assert app.state.workshield_mcp is runtime
        assert isinstance(app.state.database, Database)
        assert isinstance(app.state.file_storage, object)
        assert database_path.is_file()
        assert closed is False

    with pytest.raises(AttributeError):
        _ = app.state.workshield_mcp
    with pytest.raises(AttributeError):
        _ = app.state.database
    with pytest.raises(AttributeError):
        _ = app.state.file_storage
    assert closed is True


@pytest.mark.asyncio
async def test_lifespan_awaits_review_tasks_before_mcp_runtime_closes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def fake_open(settings):
        try:
            yield SimpleNamespace()
        finally:
            events.append("runtime-closed")

    async def pending_review() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            events.append("review-finished")

    settings = SimpleNamespace(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'ordered.db'}",
        database_echo=False,
        temp_upload_dir=tmp_path / "uploads",
        storage_cleanup_interval_seconds=60,
    )
    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    monkeypatch.setattr(lifespan_module, "open_workshield_mcp", fake_open)

    async with lifespan(app):
        task = asyncio.create_task(pending_review())
        await asyncio.sleep(0)
        app.state.review_tasks["rev_pending"] = task

    assert events == ["review-finished", "runtime-closed"]
