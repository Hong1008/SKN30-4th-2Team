"""vLLM provider의 OpenAI 호환 설정과 reasoning 변환을 검증한다."""

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.core.llm.provider.vllm import VLLMChatOpenAI, build_vllm_model
from app.core.llm.types import ReasoningMode


class FakeVLLMModel:
    calls: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.fixture(autouse=True)
def reset_fake() -> None:
    FakeVLLMModel.calls = []


def _settings() -> Settings:
    return Settings(
        app_env="local",
        llm_provider="vllm",
        llm_model="served-qwen-model",
        vllm_base_url="https://vllm.example.com/v1",
        vllm_api_key="vllm-secret",
        llm_timeout_seconds=123,
        llm_temperature=0,
        llm_top_p=1,
        llm_seed=42,
        llm_max_completion_tokens=512,
    )


@pytest.mark.parametrize(
    ("mode", "enabled"),
    [(ReasoningMode.OFF, False), (ReasoningMode.ON, True)],
)
def test_vllm_maps_qwen_thinking_to_chat_template_kwargs(
    monkeypatch: pytest.MonkeyPatch,
    mode: ReasoningMode,
    enabled: bool,
) -> None:
    monkeypatch.setattr(
        "app.core.llm.provider.vllm.VLLMChatOpenAI",
        FakeVLLMModel,
    )

    build_vllm_model(_settings(), mode)

    call = FakeVLLMModel.calls[-1]
    assert call["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": enabled}
    }
    assert "reasoning" not in call
    assert "reasoning_effort" not in call


def test_vllm_passes_openai_compatible_connection_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.llm.provider.vllm.VLLMChatOpenAI",
        FakeVLLMModel,
    )

    build_vllm_model(_settings(), ReasoningMode.OFF)

    call = FakeVLLMModel.calls[-1]
    assert call["model"] == "served-qwen-model"
    assert call["base_url"] == "https://vllm.example.com/v1"
    assert call["api_key"].get_secret_value() == "vllm-secret"
    assert call["timeout"] == 123
    assert call["use_responses_api"] is False
    assert call["temperature"] == 0
    assert call["top_p"] == 1
    assert call["seed"] == 42
    assert call["max_completion_tokens"] == 512
    assert "vllm-secret" not in repr(call["api_key"])


def test_vllm_appends_api_version_to_origin_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.llm.provider.vllm.VLLMChatOpenAI",
        FakeVLLMModel,
    )
    settings = _settings().model_copy(
        update={"vllm_base_url": "https://vllm.example.com"}
    )

    build_vllm_model(settings, ReasoningMode.OFF)

    assert FakeVLLMModel.calls[-1]["base_url"] == "https://vllm.example.com/v1"


def test_vllm_structured_output_defaults_to_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_structured_output(
        self: object,
        schema: type[Any] | None = None,
        **kwargs: object,
    ) -> object:
        captured["schema"] = schema
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(
        "langchain_openai.ChatOpenAI.with_structured_output",
        fake_structured_output,
    )
    schema = type("OutputSchema", (), {})
    model = build_vllm_model(_settings(), ReasoningMode.OFF)

    model.with_structured_output(schema)

    assert captured == {
        "schema": schema,
        "kwargs": {"method": "json_schema"},
    }


def test_vllm_sends_chat_completions_auth_thinking_and_json_schema() -> None:
    captured: dict[str, object] = {}

    class OutputSchema(BaseModel):
        answer: str

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "served-qwen-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"answer":"검증 완료"}',
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = VLLMChatOpenAI(
            model="served-qwen-model",
            api_key="wire-secret",
            base_url="https://vllm.example.com/v1",
            use_responses_api=False,
            extra_body={
                "chat_template_kwargs": {"enable_thinking": False}
            },
            http_client=client,
        )
        output = model.with_structured_output(OutputSchema).invoke("검증")

    assert output == OutputSchema(answer="검증 완료")
    assert captured["path"] == "/v1/chat/completions"
    assert captured["authorization"] == "Bearer wire-secret"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["response_format"]["type"] == "json_schema"
