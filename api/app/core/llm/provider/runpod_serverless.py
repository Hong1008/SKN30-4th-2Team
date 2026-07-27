"""RunPod Serverless Ollama worker용 LangChain chat model을 생성한다."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import SecretStr

from app.config import Settings
from app.core.llm.types import LLMConfigurationError, ReasoningMode


class _StructuredRunPodModel:
    """서비스가 사용하는 최소 structured-output Runnable 구현체."""

    def __init__(self, model: "RunPodServerlessChatModel", schema: type[Any]) -> None:
        self._model = model
        self._schema = schema

    async def ainvoke(self, prompt: str, *_args: object, **_kwargs: object) -> Any:
        output = await self._model._ainvoke_chat(
            [{"role": "user", "content": prompt}],
            response_format=self._schema.model_json_schema(),
        )
        content = _message_content(output)
        return self._schema.model_validate_json(content)


class RunPodServerlessChatModel(BaseChatModel):
    """RunPod `/runsync`으로 Ollama chat을 호출하는 동기·구조화 출력 모델."""

    model: str
    endpoint_id: str
    api_key: SecretStr
    reasoning: bool = False
    request_timeout_seconds: float = 600.0

    @property
    def _llm_type(self) -> str:
        return "runpod_serverless_ollama"

    @property
    def _identifying_params(self) -> dict[str, object]:
        return {"model": self.model, "endpoint_id": self.endpoint_id}

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **_kwargs: object,
    ) -> ChatResult:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": _ollama_messages(messages),
            "stream": False,
            "think": self.reasoning,
        }
        if stop:
            payload["options"] = {"stop": stop}
        output = self._invoke_chat(payload)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=_message_content(output)))],
        )

    def with_structured_output(self, schema: type[Any], **_kwargs: object) -> _StructuredRunPodModel:
        return _StructuredRunPodModel(self, schema)

    async def _ainvoke_chat(
        self,
        messages: list[dict[str, str]],
        *,
        response_format: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": self.reasoning,
        }
        if response_format is not None:
            payload["format"] = response_format
        return await asyncio.to_thread(self._invoke_chat, payload)

    def _invoke_chat(self, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            f"https://api.runpod.ai/v2/{self.endpoint_id}/runsync",
            data=json.dumps({"input": payload}, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.request_timeout_seconds) as response:  # noqa: S310
                envelope = json.loads(response.read())
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"RunPod Serverless 요청 실패: {error.code} {detail}") from error
        except URLError as error:
            raise RuntimeError(f"RunPod Serverless에 연결할 수 없습니다: {error.reason}") from error

        if envelope.get("status") != "COMPLETED":
            raise RuntimeError(f"RunPod 작업 미완료: {envelope}")
        output = envelope.get("output")
        if not isinstance(output, dict):
            raise RuntimeError(f"RunPod 응답 output이 올바르지 않습니다: {envelope}")
        return output


def _ollama_messages(messages: Sequence[BaseMessage]) -> list[dict[str, str]]:
    converted: list[dict[str, str]] = []
    for message in messages:
        role = "assistant" if isinstance(message, AIMessage) else "user"
        if isinstance(message, SystemMessage):
            role = "system"
        elif isinstance(message, HumanMessage):
            role = "user"
        content = message.content if isinstance(message.content, str) else json.dumps(message.content)
        converted.append({"role": role, "content": content})
    return converted


def _message_content(output: dict[str, object]) -> str:
    message = output.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise RuntimeError(f"Ollama 응답 message.content가 없습니다: {output}")
    return message["content"]


def build_runpod_serverless_model(
    settings: Settings,
    reasoning: ReasoningMode,
) -> BaseChatModel:
    if not settings.llm_model:
        raise LLMConfigurationError("LLM_MODEL이 필요합니다.")
    if settings.runpod_api_key is None:
        raise LLMConfigurationError("RUNPOD_API_KEY가 필요합니다.")
    if not settings.runpod_ollama_endpoint_id:
        raise LLMConfigurationError("RUNPOD_OLLAMA_ENDPOINT_ID가 필요합니다.")
    return RunPodServerlessChatModel(
        model=settings.llm_model,
        endpoint_id=settings.runpod_ollama_endpoint_id,
        api_key=settings.runpod_api_key,
        reasoning=reasoning is ReasoningMode.ON,
        request_timeout_seconds=settings.llm_timeout_seconds,
    )
