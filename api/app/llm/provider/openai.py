"""OpenAI용 LangChain chat model을 생성한다."""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config import Settings
from app.llm.types import LLMConfigurationError, ReasoningMode


_ON_EFFORT_PREFERENCE = ("medium", "high", "low", "minimal", "xhigh", "max")


def _profile(model: BaseChatModel) -> dict[str, Any]:
    """라이브러리가 아는 모델 capability를 빈 값에 안전하게 정규화한다."""
    return model.profile or {}


def _enabled_effort(profile: dict[str, Any]) -> str:
    """모델 profile에서 on 상태에 사용할 수 있는 추론 강도를 고른다."""
    supported = profile.get("reasoning_effort_levels") or []
    default = profile.get("reasoning_effort_default")
    if default and default != "none" and (not supported or default in supported):
        return default
    for effort in _ON_EFFORT_PREFERENCE:
        if not supported or effort in supported:
            return effort
    raise LLMConfigurationError("선택한 OpenAI 모델에서 켤 추론 수준이 없습니다.")


def build_openai_model(
    settings: Settings,
    reasoning: ReasoningMode,
) -> BaseChatModel:
    """OpenAI chat model을 capability에 맞는 reasoning 설정으로 생성한다."""
    if settings.openai_api_key is None:
        raise LLMConfigurationError("OPENAI_API_KEY가 필요합니다.")
    if not settings.llm_model:
        raise LLMConfigurationError("LLM_MODEL이 필요합니다.")

    common = {
        "model": settings.llm_model,
        "api_key": settings.openai_api_key,
    }
    probe = ChatOpenAI(**common)
    profile = _profile(probe)

    if profile.get("reasoning_output") is False:
        if reasoning is ReasoningMode.ON:
            raise LLMConfigurationError(
                "선택한 OpenAI 모델은 추론을 지원하지 않습니다."
            )
        return probe

    supported = profile.get("reasoning_effort_levels") or []
    if reasoning is ReasoningMode.OFF:
        if supported and "none" not in supported:
            raise LLMConfigurationError(
                "선택한 OpenAI 모델은 추론을 끌 수 없습니다."
            )
        effort = "none"
    else:
        effort = _enabled_effort(profile)

    return ChatOpenAI(**common, reasoning={"effort": effort})
