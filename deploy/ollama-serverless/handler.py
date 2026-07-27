"""RunPod Serverless에서 Ollama native chat 요청을 처리한다."""

from __future__ import annotations

import json
from http import HTTPStatus
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import runpod


OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"


def _ollama_chat(payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        OLLAMA_CHAT_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=600) as response:  # noqa: S310
            return json.loads(response.read())
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ValueError(f"Ollama 요청 실패: {error.code} {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Ollama에 연결할 수 없습니다: {error.reason}") from error


def handler(job: dict[str, object]) -> dict[str, object]:
    """`{"input": <Ollama /api/chat payload>}`를 native 응답으로 반환한다."""
    payload = job.get("input")
    if not isinstance(payload, dict):
        return {
            "error": "input은 Ollama /api/chat 요청 객체여야 합니다.",
            "status": HTTPStatus.BAD_REQUEST.phrase,
        }
    if not isinstance(payload.get("messages"), list):
        return {
            "error": "messages 배열이 필요합니다.",
            "status": HTTPStatus.BAD_REQUEST.phrase,
        }
    return _ollama_chat(payload)


runpod.serverless.start({"handler": handler})
