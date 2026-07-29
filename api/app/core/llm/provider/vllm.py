"""vLLM OpenAI-compatible chat model을 생성한다."""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config import Settings
from app.core.llm.policy import DEFAULT_LLM_POLICY, LLMPolicy
from app.core.llm.types import LLMConfigurationError, ReasoningMode


class VLLMChatOpenAI(ChatOpenAI):
    """vLLM이 지원하는 JSON Schema 구조화 출력을 명시적으로 사용한다."""

    def with_structured_output(
        self,
        schema: type[Any] | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        kwargs.setdefault("method", "json_schema")
        return super().with_structured_output(schema, **kwargs)


def _api_base_url(raw_url: object) -> str:
    """origin 또는 API base URL을 vLLM의 `/v1` root로 정규화한다."""
    base_url = str(raw_url).rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


def build_vllm_model(
    settings: Settings,
    reasoning: ReasoningMode,
    policy: LLMPolicy = DEFAULT_LLM_POLICY,
) -> BaseChatModel:
    """vLLM Chat Completions 모델을 Qwen thinking 설정과 함께 생성한다."""
    if not settings.llm_model:
        raise LLMConfigurationError("LLM_MODEL이 필요합니다.")
    if settings.vllm_api_key is None:
        raise LLMConfigurationError("VLLM_API_KEY가 필요합니다.")
    if settings.vllm_base_url is None:
        raise LLMConfigurationError("VLLM_BASE_URL이 필요합니다.")

    return VLLMChatOpenAI(
        model=settings.llm_model,
        api_key=settings.vllm_api_key,
        base_url=_api_base_url(settings.vllm_base_url),
        timeout=policy.timeout_seconds,
        temperature=policy.temperature,
        top_p=policy.top_p,
        seed=policy.seed,
        max_completion_tokens=policy.max_completion_tokens,
        use_responses_api=False,
        extra_body={
            "chat_template_kwargs": {
                "enable_thinking": reasoning is ReasoningMode.ON,
            }
        },
    )
