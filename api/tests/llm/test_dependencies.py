"""FastAPI LLM 의존성 계약을 검증한다."""

import inspect

from fastapi.params import Depends

from app.config import Settings, get_settings
from app.llm.dependencies import get_chat_model
from app.llm.types import ReasoningMode


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

    monkeypatch.setattr("app.llm.dependencies.create_chat_model", fake_create)

    assert get_chat_model(settings) is expected
    assert calls == [(settings, ReasoningMode.OFF)]
