"""WorkShield MCP persistent client 수명주기를 검증한다."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.llm.mcp.client import open_workshield_mcp
from app.llm.mcp.types import MCPCompatibilityError, MCPConnectionError


def _settings(transport: str = "stdio") -> Settings:
    return Settings(
        app_env="local",
        llm_provider="ollama",
        llm_model="configured-model",
        workshield_mcp_transport=transport,
    )


class FakeSession:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict) -> object:
        self.calls.append((name, arguments))
        return self.result


class FakeClient:
    def __init__(self, session: FakeSession) -> None:
        self.current_session = session
        self.session_names: list[str] = []
        self.closed = False

    @asynccontextmanager
    async def session(self, server_name: str):
        self.session_names.append(server_name)
        try:
            yield self.current_session
        finally:
            self.closed = True


@pytest.mark.asyncio
async def test_opens_one_session_and_loads_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SimpleNamespace(
        isError=False,
        structuredContent={"status": "OK", "workflows": {}},
    )
    session = FakeSession(result)
    client = FakeClient(session)
    tools = [
        SimpleNamespace(name="get_mcp_capabilities"),
        SimpleNamespace(name="review"),
    ]
    load_calls = []

    async def fake_load(current_session, **kwargs):
        load_calls.append((current_session, kwargs))
        return tools

    monkeypatch.setattr(
        "app.llm.mcp.client.create_workshield_mcp_client",
        lambda settings: client,
    )
    monkeypatch.setattr("app.llm.mcp.client.load_mcp_tools", fake_load)

    async with open_workshield_mcp(_settings()) as runtime:
        assert runtime.session is session
        assert runtime.tools == tuple(tools)
        assert runtime.capabilities == result.structuredContent
        assert runtime.supports_file_path is True
        assert client.closed is False

    assert client.session_names == ["workshield"]
    assert session.calls == [("get_mcp_capabilities", {})]
    assert load_calls[0][0] is session
    assert load_calls[0][1]["handle_tool_errors"] is True
    assert client.closed is True


@pytest.mark.asyncio
async def test_http_runtime_disables_file_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SimpleNamespace(isError=False, structuredContent={"status": "OK"})
    client = FakeClient(FakeSession(result))

    async def fake_load(session, **kwargs):
        return [SimpleNamespace(name="get_mcp_capabilities")]

    monkeypatch.setattr(
        "app.llm.mcp.client.create_workshield_mcp_client",
        lambda settings: client,
    )
    monkeypatch.setattr("app.llm.mcp.client.load_mcp_tools", fake_load)

    async with open_workshield_mcp(_settings("streamable_http")) as runtime:
        assert runtime.supports_file_path is False


@pytest.mark.asyncio
async def test_rejects_server_without_capabilities_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SimpleNamespace(isError=False, structuredContent={"status": "OK"})
    client = FakeClient(FakeSession(result))

    async def fake_load(session, **kwargs):
        return [SimpleNamespace(name="other_tool")]

    monkeypatch.setattr(
        "app.llm.mcp.client.create_workshield_mcp_client",
        lambda settings: client,
    )
    monkeypatch.setattr("app.llm.mcp.client.load_mcp_tools", fake_load)

    with pytest.raises(MCPCompatibilityError, match="get_mcp_capabilities"):
        async with open_workshield_mcp(_settings()):
            pass


@pytest.mark.asyncio
async def test_wraps_transport_initialization_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingClient:
        @asynccontextmanager
        async def session(self, server_name: str):
            raise OSError("connection refused")
            yield

    monkeypatch.setattr(
        "app.llm.mcp.client.create_workshield_mcp_client",
        lambda settings: FailingClient(),
    )

    with pytest.raises(MCPConnectionError, match="연결 또는 초기화"):
        async with open_workshield_mcp(_settings()):
            pass


@pytest.mark.asyncio
async def test_does_not_wrap_application_error_after_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SimpleNamespace(isError=False, structuredContent={"status": "OK"})
    client = FakeClient(FakeSession(result))

    async def fake_load(session, **kwargs):
        return [SimpleNamespace(name="get_mcp_capabilities")]

    monkeypatch.setattr(
        "app.llm.mcp.client.create_workshield_mcp_client",
        lambda settings: client,
    )
    monkeypatch.setattr("app.llm.mcp.client.load_mcp_tools", fake_load)

    with pytest.raises(LookupError, match="application failure"):
        async with open_workshield_mcp(_settings()):
            raise LookupError("application failure")

    assert client.closed is True
