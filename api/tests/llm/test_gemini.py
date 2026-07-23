"""Gemini LLM 생성과 reasoning 변환을 검증한다."""

from typing import Any

import pytest

from app.config import Settings
from app.llm.provider.gemini import build_gemini_model
from app.llm.types import LLMConfigurationError, ReasoningMode


class FakeGeminiModel:
    calls: list[dict[str, Any]] = []
    profile_override: dict[str, Any] | None = {
        "reasoning_output": True,
        "reasoning_effort_levels": ["minimal", "low", "medium", "high"],
    }

    def __init__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        self.profile = self.profile_override


@pytest.fixture(autouse=True)
def reset_fake() -> None:
    FakeGeminiModel.calls = []
    FakeGeminiModel.profile_override = {
        "reasoning_output": True,
        "reasoning_effort_levels": ["minimal", "low", "medium", "high"],
    }


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "local",
        "llm_provider": "gemini",
        "llm_model": "runtime-selected-model",
        "gemini_api_key": "gemini-secret",
    }
    values.update(overrides)
    return Settings(**values)


def test_gemini_maps_reasoning_on_without_model_name_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.llm.provider.gemini.ChatGoogleGenerativeAI", FakeGeminiModel)

    build_gemini_model(_settings(), ReasoningMode.ON)

    assert FakeGeminiModel.calls[-1]["model"] == "runtime-selected-model"
    assert FakeGeminiModel.calls[-1]["thinking_level"] == "high"


@pytest.mark.parametrize(
    ("mode", "thinking_level"),
    [(ReasoningMode.OFF, "minimal"), (ReasoningMode.ON, "high")],
)
def test_gemma_style_boolean_reasoning_maps_to_minimal_and_high(
    monkeypatch: pytest.MonkeyPatch,
    mode: ReasoningMode,
    thinking_level: str,
) -> None:
    FakeGeminiModel.profile_override = {"reasoning_output": True}
    monkeypatch.setattr("app.llm.provider.gemini.ChatGoogleGenerativeAI", FakeGeminiModel)

    build_gemini_model(_settings(), mode)

    assert FakeGeminiModel.calls[-1]["thinking_level"] == thinking_level


def test_gemini_passes_selected_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeGeminiModel.profile_override = {"reasoning_output": True}
    monkeypatch.setattr("app.llm.provider.gemini.ChatGoogleGenerativeAI", FakeGeminiModel)

    build_gemini_model(_settings(), ReasoningMode.OFF)

    api_key = FakeGeminiModel.calls[-1]["api_key"]
    assert api_key.get_secret_value() == "gemini-secret"
    assert "gemini-secret" not in repr(api_key)


def test_gemini_rejects_reasoning_on_for_unsupported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeGeminiModel.profile_override = {"reasoning_output": False}
    monkeypatch.setattr("app.llm.provider.gemini.ChatGoogleGenerativeAI", FakeGeminiModel)

    with pytest.raises(LLMConfigurationError, match="추론을 지원하지 않습니다"):
        build_gemini_model(_settings(), ReasoningMode.ON)


def test_gemini_rejects_unavailable_reasoning_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeGeminiModel.profile_override = {
        "reasoning_output": True,
        "reasoning_effort_levels": ["minimal", "low"],
    }
    monkeypatch.setattr("app.llm.provider.gemini.ChatGoogleGenerativeAI", FakeGeminiModel)

    with pytest.raises(LLMConfigurationError, match="high 추론 수준"):
        build_gemini_model(_settings(), ReasoningMode.ON)


def test_gemini_rejects_off_for_default_on_reasoning_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeGeminiModel.profile_override = {
        "reasoning_output": True,
        "reasoning_effort_levels": ["minimal", "low", "medium", "high"],
        "reasoning_effort_default": "minimal",
    }
    monkeypatch.setattr("app.llm.provider.gemini.ChatGoogleGenerativeAI", FakeGeminiModel)

    with pytest.raises(LLMConfigurationError, match="추론을 끌 수 없습니다"):
        build_gemini_model(_settings(), ReasoningMode.OFF)
