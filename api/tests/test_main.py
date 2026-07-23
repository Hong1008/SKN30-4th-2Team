"""FastAPI 애플리케이션의 MCP lifespan 연결을 검증한다."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import main
from app.llm.mcp.types import WorkShieldMCPRuntime


@pytest.mark.asyncio
async def test_lifespan_exposes_and_cleans_mcp_runtime(
    monkeypatch: pytest.MonkeyPatch,
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

    monkeypatch.setattr(main, "open_workshield_mcp", fake_open)

    async with main.lifespan(main.app):
        assert main.app.state.workshield_mcp is runtime
        assert closed is False

    with pytest.raises(AttributeError):
        _ = main.app.state.workshield_mcp
    assert closed is True
