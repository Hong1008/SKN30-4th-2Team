"""Ollama LLM 생성과 reasoning 변환을 검증한다."""

from typing import Any

import pytest

from app.config import Settings
from app.core.llm.provider.ollama import build_ollama_model
from app.core.llm.types import ReasoningMode


class FakeOllamaModel:
    calls: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.fixture(autouse=True)
def reset_fake() -> None:
    FakeOllamaModel.calls = []


def _settings(*, ollama_api_key: str | None = None) -> Settings:
    return Settings(
        app_env="local",
        llm_provider="ollama",
        llm_model="runtime-selected-model",
        ollama_base_url="http://ollama.internal:11434",
        ollama_api_key=ollama_api_key,
    )


@pytest.mark.parametrize(
    ("mode", "enabled"),
    [(ReasoningMode.OFF, False), (ReasoningMode.ON, True)],
)
def test_ollama_maps_reasoning_without_model_name_branch(
    monkeypatch: pytest.MonkeyPatch,
    mode: ReasoningMode,
    enabled: bool,
) -> None:
    monkeypatch.setattr("app.core.llm.provider.ollama.ChatOllama", FakeOllamaModel)

    build_ollama_model(_settings(), mode)

    assert FakeOllamaModel.calls == [
        {
            "model": "runtime-selected-model",
            "base_url": "http://ollama.internal:11434/",
            "reasoning": enabled,
            "client_kwargs": {},
        }
    ]


def test_ollama_sends_pod_api_key_as_bearer_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.llm.provider.ollama.ChatOllama", FakeOllamaModel)

    build_ollama_model(_settings(ollama_api_key="ollama-secret"), ReasoningMode.OFF)

    assert FakeOllamaModel.calls[-1]["client_kwargs"] == {
        "headers": {"Authorization": "Bearer ollama-secret"},
    }
