"""환경 설정과 FastAPI 의존성 주입 계약을 검증한다."""

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.config import MCPTransport, Settings, get_settings
from main import app


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()

    assert get_settings() is get_settings()


def test_production_rejects_external_provider() -> None:
    with pytest.raises(ValidationError, match="LLM_PROVIDER=ollama"):
        Settings(app_env="prod", llm_provider="openai")


def test_mcp_transport_defaults_to_stdio() -> None:
    settings = Settings(
        app_env="local",
        llm_provider="ollama",
        llm_model="configured-model",
        workshield_mcp_transport="stdio",
    )

    assert settings.workshield_mcp_transport is MCPTransport.STDIO


def test_mcp_timeout_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="local",
            llm_provider="ollama",
            llm_model="configured-model",
            workshield_mcp_timeout=0,
        )


def test_health_declares_settings_dependency() -> None:
    route = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/health"
    )

    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}

    assert get_settings in dependency_calls
