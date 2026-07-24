"""FastAPI 애플리케이션 팩토리와 MCP lifespan 연결을 검증한다."""

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.lifespan as lifespan_module
from app.db.database import Database
from app.factory import create_app
from app.llm.mcp.types import WorkShieldMCPRuntime
from app.lifespan import lifespan
from main import app


def test_create_app_registers_common_routes() -> None:
    created_app = create_app()
    route_paths = set(created_app.openapi()["paths"])

    assert created_app.title == "WorkShield API"
    assert "/health/live" in route_paths
    assert "/health/ready" in route_paths


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
    )
    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    monkeypatch.setattr(lifespan_module, "open_workshield_mcp", fake_open)

    async with lifespan(app):
        assert app.state.workshield_mcp is runtime
        assert isinstance(app.state.database, Database)
        assert database_path.is_file()
        assert closed is False

    with pytest.raises(AttributeError):
        _ = app.state.workshield_mcp
    with pytest.raises(AttributeError):
        _ = app.state.database
    assert closed is True
