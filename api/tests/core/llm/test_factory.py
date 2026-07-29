"""LLM provider factory의 공통 계약을 검증한다."""

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.core.llm import LLMConfigurationError, ReasoningMode, create_chat_model
from app.core.llm.policy import LLMPolicy


def _settings(provider: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "local",
        "llm_provider": provider,
        "llm_model": "configured-model",
        "openai_api_key": "openai-secret",
        "gemini_api_key": "gemini-secret",
        "runpod_serverless_api_key": "runpod-secret",
        "runpod_ollama_endpoint_id": "endpoint-id",
        "ollama_base_url": "http://ollama.internal:11434",
        "vllm_base_url": "https://vllm.internal/v1",
        "vllm_api_key": "vllm-secret",
    }
    values.update(overrides)
    return Settings(**values)


def test_factory_creates_selected_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = object()
    calls: list[tuple[Settings, ReasoningMode, LLMPolicy]] = []

    def fake_builder(
        settings: Settings,
        reasoning: ReasoningMode,
        policy: LLMPolicy,
    ) -> object:
        calls.append((settings, reasoning, policy))
        return expected

    monkeypatch.setattr("app.core.llm.factory.PROVIDER_BUILDERS", {"gemini": fake_builder})
    settings = _settings("gemini")

    result = create_chat_model(settings)

    assert result is expected
    assert calls == [(settings, ReasoningMode.OFF, LLMPolicy())]


def test_factory_requires_model_name() -> None:
    with pytest.raises(LLMConfigurationError, match="LLM_MODEL"):
        create_chat_model(_settings("ollama", llm_model=None))


def test_factory_rejects_missing_selected_provider_key() -> None:
    with pytest.raises(LLMConfigurationError, match="GEMINI_API_KEY"):
        create_chat_model(_settings("gemini", gemini_api_key=None))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"runpod_serverless_api_key": None}, "RUNPOD_SERVERLESS_API_KEY"),
        ({"runpod_ollama_endpoint_id": None}, "RUNPOD_OLLAMA_ENDPOINT_ID"),
    ],
)
def test_factory_requires_runpod_serverless_configuration(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(LLMConfigurationError, match=message):
        create_chat_model(_settings("runpod_serverless", **overrides))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"vllm_api_key": None}, "VLLM_API_KEY"),
        ({"vllm_base_url": None}, "VLLM_BASE_URL"),
    ],
)
def test_factory_requires_vllm_configuration(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(LLMConfigurationError, match=message):
        create_chat_model(_settings("vllm", **overrides))


def test_configuration_error_does_not_expose_secret() -> None:
    secret = "must-not-appear"
    settings = _settings("openai", openai_api_key=SecretStr(secret))

    with pytest.raises(LLMConfigurationError) as exc_info:
        create_chat_model(settings, reasoning="invalid")  # type: ignore[arg-type]

    assert secret not in str(exc_info.value)


def test_factory_rejects_unknown_provider_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.llm.factory.PROVIDER_BUILDERS", {})

    with pytest.raises(LLMConfigurationError, match="지원하지 않는 LLM provider"):
        create_chat_model(_settings("openai"))


def test_factory_returns_langchain_model_from_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = SimpleNamespace(model="configured-model")
    monkeypatch.setattr(
        "app.core.llm.factory.PROVIDER_BUILDERS",
        {"ollama": lambda settings, reasoning, policy: model},
    )

    assert create_chat_model(_settings("ollama")) is model
