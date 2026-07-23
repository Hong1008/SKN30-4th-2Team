"""LLM provider factory의 공통 계약을 검증한다."""

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.llm import LLMConfigurationError, ReasoningMode, create_chat_model


def _settings(provider: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "local",
        "llm_provider": provider,
        "llm_model": "configured-model",
        "openai_api_key": "openai-secret",
        "gemini_api_key": "gemini-secret",
        "ollama_base_url": "http://ollama.internal:11434",
    }
    values.update(overrides)
    return Settings(**values)


def test_factory_creates_selected_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = object()
    calls: list[tuple[Settings, ReasoningMode]] = []

    def fake_builder(settings: Settings, reasoning: ReasoningMode) -> object:
        calls.append((settings, reasoning))
        return expected

    monkeypatch.setattr("app.llm.factory.PROVIDER_BUILDERS", {"gemini": fake_builder})
    settings = _settings("gemini")

    result = create_chat_model(settings)

    assert result is expected
    assert calls == [(settings, ReasoningMode.OFF)]


def test_factory_requires_model_name() -> None:
    with pytest.raises(LLMConfigurationError, match="LLM_MODEL"):
        create_chat_model(_settings("ollama", llm_model=None))


def test_factory_rejects_missing_selected_provider_key() -> None:
    with pytest.raises(LLMConfigurationError, match="GEMINI_API_KEY"):
        create_chat_model(_settings("gemini", gemini_api_key=None))


def test_configuration_error_does_not_expose_secret() -> None:
    secret = "must-not-appear"
    settings = _settings("openai", openai_api_key=SecretStr(secret))

    with pytest.raises(LLMConfigurationError) as exc_info:
        create_chat_model(settings, reasoning="invalid")  # type: ignore[arg-type]

    assert secret not in str(exc_info.value)


def test_factory_rejects_unknown_provider_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.llm.factory.PROVIDER_BUILDERS", {})

    with pytest.raises(LLMConfigurationError, match="지원하지 않는 LLM provider"):
        create_chat_model(_settings("openai"))


def test_factory_returns_langchain_model_from_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = SimpleNamespace(model="configured-model")
    monkeypatch.setattr(
        "app.llm.factory.PROVIDER_BUILDERS",
        {"ollama": lambda settings, reasoning: model},
    )

    assert create_chat_model(_settings("ollama")) is model
