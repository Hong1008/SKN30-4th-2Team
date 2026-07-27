"""RunPod Serverless Ollama provider의 요청 외피를 검증한다."""

import json
from typing import Any

from pydantic import SecretStr

from app.core.llm.provider.runpod_serverless import RunPodServerlessChatModel


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_runpod_serverless_wraps_native_ollama_payload(
    monkeypatch: Any,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse({
            "status": "COMPLETED",
            "output": {"message": {"role": "assistant", "content": "{}"}},
        })

    monkeypatch.setattr(
        "app.core.llm.provider.runpod_serverless.urlopen",
        fake_urlopen,
    )
    model = RunPodServerlessChatModel(
        model="hf.co/example/model",
        endpoint_id="endpoint-id",
        api_key=SecretStr("runpod-secret"),
        request_timeout_seconds=321,
    )

    output = model._invoke_chat({"model": "hf.co/example/model", "messages": []})

    assert output == {"message": {"role": "assistant", "content": "{}"}}
    assert captured == {
        "url": "https://api.runpod.ai/v2/endpoint-id/runsync",
        "headers": {
            "Authorization": "Bearer runpod-secret",
            "Content-type": "application/json",
        },
        "body": {"input": {"model": "hf.co/example/model", "messages": []}},
        "timeout": 321,
    }
