"""Ollama용 LangChain chat model을 생성한다."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama

from app.config import Settings
from app.llm.types import LLMConfigurationError, ReasoningMode


def build_ollama_model(
    settings: Settings,
    reasoning: ReasoningMode,
) -> BaseChatModel:
    """Ollama의 native think boolean으로 reasoning on/off를 전달한다."""
    if not settings.llm_model:
        raise LLMConfigurationError("LLM_MODEL이 필요합니다.")

    return ChatOllama(
        model=settings.llm_model,
        base_url=str(settings.ollama_base_url),
        reasoning=reasoning is ReasoningMode.ON,
    )
