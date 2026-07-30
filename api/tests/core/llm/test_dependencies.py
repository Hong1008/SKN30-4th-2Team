"""FastAPI LLM 의존성 계약을 검증한다."""

import inspect
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.params import Depends
from starlette.requests import Request

from app.config import Settings, get_settings
from app.core.llm.dependencies import (
    ROUTER_LLM_POLICY,
    get_chat_model,
    get_mcp_runtime,
    get_mcp_tools,
    get_router_model,
)
from app.core.llm.mcp.types import WorkShieldMCPRuntime
from app.core.llm.types import ReasoningMode


def test_get_chat_model_uses_settings_dependency() -> None:
    parameter = inspect.signature(get_chat_model).parameters["settings"]
    metadata = parameter.annotation.__metadata__

    assert any(
        isinstance(item, Depends) and item.dependency is get_settings
        for item in metadata
    )


def test_get_chat_model_defaults_reasoning_to_off(monkeypatch) -> None:
    settings = Settings(
        app_env="local",
        llm_provider="ollama",
        llm_model="runtime-selected-model",
    )
    expected = object()
    calls = []

    def fake_create(current_settings, reasoning):
        calls.append((current_settings, reasoning))
        return expected

    monkeypatch.setattr("app.core.llm.dependencies.create_chat_model", fake_create)

    assert get_chat_model(settings) is expected
    assert calls == [(settings, ReasoningMode.OFF)]


def test_get_router_model_uses_short_zero_temperature_policy(monkeypatch) -> None:
    settings = Settings(
        app_env="local",
        llm_provider="ollama",
        llm_model="runtime-selected-model",
    )
    expected = object()
    calls = []

    def fake_create(current_settings, reasoning, policy):
        calls.append((current_settings, reasoning, policy))
        return expected

    monkeypatch.setattr("app.core.llm.dependencies.create_chat_model", fake_create)

    assert get_router_model(settings) is expected
    assert calls == [(settings, ReasoningMode.OFF, ROUTER_LLM_POLICY)]
    assert ROUTER_LLM_POLICY.temperature == 0
    assert ROUTER_LLM_POLICY.max_completion_tokens == 16


@pytest.mark.asyncio
async def test_get_mcp_runtime_reads_lifespan_state() -> None:
    app = FastAPI()
    runtime = WorkShieldMCPRuntime(
        client=SimpleNamespace(),
        session=SimpleNamespace(),
        tools=(SimpleNamespace(name="tool"),),
        capabilities={"status": "OK"},
        supports_file_path=True,
    )
    app.state.workshield_mcp = runtime
    request = Request({"type": "http", "app": app})

    assert await get_mcp_runtime(request) is runtime
    assert get_mcp_tools(runtime) is runtime.tools


@pytest.mark.asyncio
async def test_get_mcp_runtime_returns_503_before_lifespan() -> None:
    request = Request({"type": "http", "app": FastAPI()})

    with pytest.raises(HTTPException) as exc_info:
        await get_mcp_runtime(request)

    assert exc_info.value.status_code == 503


def test_get_mcp_tools_uses_runtime_dependency() -> None:
    parameter = inspect.signature(get_mcp_tools).parameters["runtime"]
    metadata = parameter.annotation.__metadata__

    assert any(
        isinstance(item, Depends) and item.dependency is get_mcp_runtime
        for item in metadata
    )
