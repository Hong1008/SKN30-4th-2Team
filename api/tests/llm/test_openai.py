"""OpenAI LLM 생성과 reasoning 변환을 검증한다."""

from typing import Any

import pytest

from app.config import Settings
from app.llm.provider.openai import build_openai_model
from app.llm.types import LLMConfigurationError, ReasoningMode


class FakeOpenAIModel:
    calls: list[dict[str, Any]] = []
    profile_override: dict[str, Any] | None = {
        "reasoning_output": True,
        "reasoning_effort_levels": ["none", "low", "medium", "high"],
        "reasoning_effort_default": "medium",
    }

    def __init__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        self.profile = self.profile_override


@pytest.fixture(autouse=True)
def reset_fake() -> None:
    FakeOpenAIModel.calls = []
    FakeOpenAIModel.profile_override = {
        "reasoning_output": True,
        "reasoning_effort_levels": ["none", "low", "medium", "high"],
        "reasoning_effort_default": "medium",
    }


def _settings() -> Settings:
    return Settings(
        app_env="local",
        llm_provider="openai",
        llm_model="runtime-selected-model",
        openai_api_key="openai-secret",
    )


@pytest.mark.parametrize(
    ("mode", "effort"),
    [(ReasoningMode.OFF, "none"), (ReasoningMode.ON, "medium")],
)
def test_openai_maps_reasoning(
    monkeypatch: pytest.MonkeyPatch,
    mode: ReasoningMode,
    effort: str,
) -> None:
    monkeypatch.setattr("app.llm.provider.openai.ChatOpenAI", FakeOpenAIModel)

    build_openai_model(_settings(), mode)

    assert FakeOpenAIModel.calls[-1]["reasoning"] == {"effort": effort}


def test_openai_passes_runtime_model_and_selected_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.llm.provider.openai.ChatOpenAI", FakeOpenAIModel)

    build_openai_model(_settings(), ReasoningMode.OFF)

    call = FakeOpenAIModel.calls[-1]
    assert call["model"] == "runtime-selected-model"
    assert call["api_key"].get_secret_value() == "openai-secret"
    assert "openai-secret" not in repr(call["api_key"])


def test_openai_rejects_off_for_always_on_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeOpenAIModel.profile_override = {
        "reasoning_output": True,
        "reasoning_effort_levels": ["high"],
        "reasoning_effort_default": "high",
    }
    monkeypatch.setattr("app.llm.provider.openai.ChatOpenAI", FakeOpenAIModel)

    with pytest.raises(LLMConfigurationError, match="추론을 끌 수 없습니다"):
        build_openai_model(_settings(), ReasoningMode.OFF)


def test_openai_rejects_on_for_unsupported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeOpenAIModel.profile_override = {"reasoning_output": False}
    monkeypatch.setattr("app.llm.provider.openai.ChatOpenAI", FakeOpenAIModel)

    with pytest.raises(LLMConfigurationError, match="추론을 지원하지 않습니다"):
        build_openai_model(_settings(), ReasoningMode.ON)
