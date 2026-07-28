"""MCP 참조형 LLM 평가 fixture의 무결성을 검증한다."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import httpx
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from app.config import Settings
from app.core.common.errors import ExternalServiceTimeoutError
from app.core.llm.evaluation import (
    load_evaluation_suite,
    resolve_evaluation_fixtures,
)
from scripts.run_llm_evaluation import (
    RecordingChatModel,
    _assess_error_result,
    _request_text,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SUITE_PATH = (
    REPOSITORY_ROOT / "api/evaluation/llm/fixtures/suggestions_v1.json"
)


def test_evaluation_suite_resolves_eight_unique_mcp_cases() -> None:
    suite = load_evaluation_suite(SUITE_PATH)
    fixtures = resolve_evaluation_fixtures(
        suite,
        repository_root=REPOSITORY_ROOT,
    )

    assert len(fixtures) == 8
    assert len({item.overlay.fixture_id for item in fixtures}) == 8
    assert len({item.overlay.mcp_case_id for item in fixtures}) == 8
    assert all(item.standard["clause_id"] for item in fixtures)


def test_evaluation_suite_covers_required_risk_cases() -> None:
    suite = load_evaluation_suite(SUITE_PATH)
    fixtures = {item.fixture_id: item for item in suite.fixtures}

    assert "30일" in fixtures["numeric_grounding"].provided_inputs.values()
    assert "пользователь" in fixtures["prompt_injection"].purpose
    assert all(item.required_source_keys for item in suite.fixtures)


class _RecordedOutput(BaseModel):
    answer: str


class _RawStructuredRunnable:
    async def ainvoke(self, prompt: str) -> dict[str, object]:
        assert prompt == "검증"
        return {
            "raw": AIMessage(
                content='{"answer":"완료"}',
                response_metadata={"finish_reason": "stop"},
                usage_metadata={
                    "input_tokens": 120,
                    "output_tokens": 34,
                    "total_tokens": 154,
                },
            ),
            "parsed": _RecordedOutput(answer="완료"),
            "parsing_error": None,
        }


class _RawRecordingDelegate:
    def __init__(self) -> None:
        self.include_raw: bool | None = None

    def with_structured_output(
        self,
        schema: type[Any],
        *,
        include_raw: bool,
    ) -> _RawStructuredRunnable:
        assert schema is _RecordedOutput
        self.include_raw = include_raw
        return _RawStructuredRunnable()


class _LengthError(Exception):
    def __init__(self) -> None:
        self.completion = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=900,
                completion_tokens=1000,
                total_tokens=1900,
            ),
            choices=[SimpleNamespace(finish_reason="length")],
        )


class _LengthStructuredRunnable:
    async def ainvoke(self, prompt: str) -> object:
        raise _LengthError


class _LengthRecordingDelegate:
    def with_structured_output(
        self,
        schema: type[Any],
        *,
        include_raw: bool,
    ) -> _LengthStructuredRunnable:
        return _LengthStructuredRunnable()


@pytest.mark.asyncio
async def test_recording_model_collects_per_call_usage_and_finish_reason() -> None:
    delegate = _RawRecordingDelegate()
    model = RecordingChatModel(delegate)

    result = await model.with_structured_output(_RecordedOutput).ainvoke("검증")

    assert result == _RecordedOutput(answer="완료")
    assert delegate.include_raw is True
    assert model.records[0]["finish_reason"] == "stop"
    assert model.records[0]["token_usage"] == {
        "prompt_tokens": 120,
        "completion_tokens": 34,
        "total_tokens": 154,
    }


@pytest.mark.asyncio
async def test_recording_model_collects_usage_from_length_error() -> None:
    model = RecordingChatModel(_LengthRecordingDelegate())

    with pytest.raises(_LengthError):
        await model.with_structured_output(_RecordedOutput).ainvoke("검증")

    assert model.records[0]["finish_reason"] == "length"
    assert model.records[0]["token_usage"] == {
        "prompt_tokens": 900,
        "completion_tokens": 1000,
        "total_tokens": 1900,
    }


def test_request_text_uses_httpx_with_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_get(
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        captured.update(url=url, headers=headers, timeout=timeout)
        return httpx.Response(
            200,
            text='{"status":"ok"}',
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("scripts.run_llm_evaluation.httpx.get", fake_get)
    settings = Settings(
        vllm_api_key="test-secret",
        vllm_base_url="https://vllm.example.com",
    )

    result = _request_text("https://vllm.example.com/version", settings)

    assert result == '{"status":"ok"}'
    assert captured["headers"] == {
        "Authorization": "Bearer test-secret",
        "User-Agent": "OpenAI/Python 2.15.0",
    }
    assert captured["timeout"] == 30


def test_evaluation_converts_timeout_to_failed_case() -> None:
    suite = load_evaluation_suite(SUITE_PATH)
    fixture = resolve_evaluation_fixtures(
        suite,
        repository_root=REPOSITORY_ROOT,
    )[0]
    error = ExternalServiceTimeoutError(
        code="LLM_TIMEOUT",
        message="시간 초과",
    )

    result = _assess_error_result(
        fixture,
        attempts=[{"status": "error", "error_type": "TimeoutError"}],
        elapsed_seconds=60,
        repetition=1,
        error=error,
    )

    assert result["passed"] is False
    assert result["response"]["outcome"] == "LLM_TIMEOUT"
    assert result["error_type"] == "ExternalServiceTimeoutError"
