"""Google Gemini API용 LangChain chat model을 생성한다."""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import Settings
from app.llm.types import LLMConfigurationError, ReasoningMode


_THINKING_LEVEL = {
    ReasoningMode.OFF: "minimal",
    ReasoningMode.ON: "high",
}


def _profile(model: BaseChatModel) -> dict[str, Any]:
    """라이브러리가 아는 모델 capability를 빈 값에 안전하게 정규화한다."""
    return model.profile or {}


def build_gemini_model(
    settings: Settings,
    reasoning: ReasoningMode,
) -> BaseChatModel:
    """Gemini/Gemma chat model을 reasoning on/off 계약에 맞춰 생성한다."""
    if settings.gemini_api_key is None:
        raise LLMConfigurationError("GEMINI_API_KEY가 필요합니다.")
    if not settings.llm_model:
        raise LLMConfigurationError("LLM_MODEL이 필요합니다.")

    common = {
        "model": settings.llm_model,
        "api_key": settings.gemini_api_key,
        "vertexai": False,
    }
    probe = ChatGoogleGenerativeAI(**common)
    profile = _profile(probe)

    if profile.get("reasoning_output") is False:
        if reasoning is ReasoningMode.ON:
            raise LLMConfigurationError(
                "선택한 Gemini 모델은 추론을 지원하지 않습니다."
            )
        return probe

    supported_levels = profile.get("reasoning_effort_levels")
    if reasoning is ReasoningMode.OFF and supported_levels:
        raise LLMConfigurationError(
            "선택한 Gemini 모델은 추론을 끌 수 없습니다."
        )

    thinking_level = _THINKING_LEVEL[reasoning]
    if supported_levels and thinking_level not in supported_levels:
        raise LLMConfigurationError(
            f"선택한 Gemini 모델은 {thinking_level} 추론 수준을 지원하지 않습니다."
        )

    return ChatGoogleGenerativeAI(
        **common,
        thinking_level=thinking_level,
    )
