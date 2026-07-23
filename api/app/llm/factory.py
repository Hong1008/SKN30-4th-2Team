"""설정에 따라 LLM provider 구현체를 선택한다."""

from collections.abc import Callable

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import LLMProvider, Settings
from app.llm.provider.gemini import build_gemini_model
from app.llm.provider.ollama import build_ollama_model
from app.llm.provider.openai import build_openai_model
from app.llm.types import LLMConfigurationError, ReasoningMode


ProviderBuilder = Callable[[Settings, ReasoningMode], BaseChatModel]

PROVIDER_BUILDERS: dict[str, ProviderBuilder] = {
    LLMProvider.OPENAI.value: build_openai_model,
    LLMProvider.GEMINI.value: build_gemini_model,
    LLMProvider.OLLAMA.value: build_ollama_model,
}


def create_chat_model(
    settings: Settings,
    reasoning: ReasoningMode = ReasoningMode.OFF,
) -> BaseChatModel:
    """선택 provider의 chat model을 만들며 추론은 기본적으로 끈다."""
    try:
        normalized_reasoning = ReasoningMode(reasoning)
    except ValueError as error:
        raise LLMConfigurationError(
            "추론 모드는 'off' 또는 'on'이어야 합니다."
        ) from error

    if not settings.llm_model:
        raise LLMConfigurationError("LLM_MODEL이 필요합니다.")

    provider = settings.llm_provider.value
    if provider == LLMProvider.OPENAI.value and settings.openai_api_key is None:
        raise LLMConfigurationError("OPENAI_API_KEY가 필요합니다.")
    if provider == LLMProvider.GEMINI.value and settings.gemini_api_key is None:
        raise LLMConfigurationError("GEMINI_API_KEY가 필요합니다.")

    builder = PROVIDER_BUILDERS.get(provider)
    if builder is None:
        raise LLMConfigurationError(f"지원하지 않는 LLM provider입니다: {provider}")
    return builder(settings, normalized_reasoning)
