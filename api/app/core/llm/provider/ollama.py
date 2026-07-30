"""Ollama용 LangChain chat model을 생성한다."""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama

from app.config import Settings
from app.core.llm.policy import DEFAULT_LLM_POLICY, LLMPolicy
from app.core.llm.types import LLMConfigurationError, ReasoningMode


class OllamaChatModel(ChatOllama):
    """Ollama native JSON Schema 구조화 출력을 명시적으로 유지한다."""

    def with_structured_output(
        self,
        schema: type[Any] | dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        kwargs.setdefault("method", "json_schema")
        return super().with_structured_output(schema, **kwargs)


def build_ollama_model(
    settings: Settings,
    reasoning: ReasoningMode,
    policy: LLMPolicy = DEFAULT_LLM_POLICY,
) -> BaseChatModel:
    """Ollama의 native think boolean으로 reasoning on/off를 전달한다."""
    if not settings.llm_model:
        raise LLMConfigurationError("LLM_MODEL이 필요합니다.")

    return OllamaChatModel(
        model=settings.llm_model,
        base_url=str(settings.ollama_base_url),
        reasoning=reasoning is ReasoningMode.ON,
        temperature=policy.temperature,
        top_p=policy.top_p,
        seed=policy.seed,
        num_predict=policy.max_completion_tokens,
    )
