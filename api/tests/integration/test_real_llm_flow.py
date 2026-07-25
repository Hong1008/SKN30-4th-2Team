"""실제 설정 LLM의 구조화 출력과 API 안전 경계를 검증한다."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.chat.schemas import ChatRequest
from app.chat.service import answer_review_question
from app.config import Settings
from app.llm.factory import create_chat_model
from app.reviews.domain import MCPReviewStatus, Review, ReviewState
from app.suggestions.schemas import SuggestionRequest
from app.suggestions.service import generate_suggestion


pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class GroundingTool:
    """LLM 평가에서 법령 네트워크 변수를 제거하는 고정 grounding 도구."""

    name = "get_category_grounding"

    async def ainvoke(self, payload: dict[str, object]) -> dict[str, object]:
        assert payload == {
            "contract_type": "SW_FREELANCE",
            "category": "LIABILITY",
        }
        return {
            "status": "OK",
            "category": {
                "code": "LIABILITY",
                "label": "책임·손해배상",
            },
            "grounding": [
                {
                    "source_id": "law_1",
                    "law_name": "민법",
                    "article": "제390조",
                    "text": "채무불이행으로 인한 손해배상에 관한 참고 원문입니다.",
                    "source": "국가법령정보센터",
                }
            ],
        }


class RecordingStructuredModel:
    """서비스가 받은 실제 구조화 출력을 테스트 로그에 보존한다."""

    def __init__(self, delegate: object, outputs: list[object]) -> None:
        self._delegate = delegate
        self._outputs = outputs

    async def ainvoke(self, prompt: str) -> object:
        output = await self._delegate.ainvoke(prompt)
        self._outputs.append(output)
        return output


class RecordingChatModel:
    """실제 모델 호출은 위임하고 구조화 결과만 기록한다."""

    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self.outputs: list[object] = []

    def with_structured_output(self, schema: type) -> RecordingStructuredModel:
        return RecordingStructuredModel(
            self._delegate.with_structured_output(schema),
            self.outputs,
        )


def _serializable(value: object) -> object:
    model_dump = getattr(value, "model_dump", None)
    return model_dump(mode="json") if callable(model_dump) else value


def _settings() -> Settings:
    legacy_ollama = os.getenv("RUN_OLLAMA_INTEGRATION") == "1"
    if os.getenv("RUN_LLM_INTEGRATION") != "1" and not legacy_ollama:
        pytest.skip("RUN_LLM_INTEGRATION=1일 때만 실제 LLM 테스트를 실행합니다.")
    configured = Settings()
    provider = os.getenv("LLM_INTEGRATION_PROVIDER") or (
        "ollama" if legacy_ollama else configured.llm_provider.value
    )
    model = (
        os.getenv("LLM_INTEGRATION_MODEL")
        or os.getenv("OLLAMA_INTEGRATION_MODEL")
        or configured.llm_model
    )
    if not model:
        pytest.skip("LLM_INTEGRATION_MODEL 또는 LLM_MODEL에 실제 모델명이 필요합니다.")
    return Settings(
        app_env="local",
        llm_provider=provider,
        llm_model=model,
        llm_timeout_seconds=float(
            os.getenv(
                "LLM_TEST_TIMEOUT",
                os.getenv("OLLAMA_TEST_TIMEOUT", "180"),
            )
        ),
        workshield_mcp_timeout=30,
    )


def _review() -> Review:
    now = datetime.now(UTC)
    return Review(
        id="rev_llm",
        session_id="ses_llm",
        idempotency_key="llm-evaluation",
        state=ReviewState.COMPLETED,
        contract_type="SW_FREELANCE",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        mcp_review_status=MCPReviewStatus.OK,
        result={
            "status": "OK",
            "contract_type": "SW_FREELANCE",
            "clause_results": [
                {
                    "user_clause_id": "uc_rev_llm_1",
                    "user_clause": "손해배상 책임의 범위는 상호 협의하여 정한다.",
                    "deviation": "NONE",
                    "match": {
                        "status": "CANDIDATE_SELECTED",
                        "standard": {
                            "clause_id": "std_liability_1",
                            "contract_type": "SW_FREELANCE",
                            "category": "LIABILITY",
                            "title": "손해배상",
                            "text": "귀책사유가 있는 당사자는 발생한 손해를 배상한다.",
                            "source": "SW 프리랜서 표준계약서",
                            "version": "2020",
                        },
                        "score": 0.95,
                    },
                    "toxic_patterns": [],
                }
            ],
            "missing_standard_clauses": [],
            "message": None,
        },
        started_at=now,
        completed_at=now,
    )


async def test_real_llm_chat_structured_output() -> None:
    """Chat이 검증 가능한 ID와 비어 있지 않은 답변을 생성한다."""
    settings = _settings()
    model = RecordingChatModel(create_chat_model(settings))
    runtime = SimpleNamespace(tools=(GroundingTool(),))
    review = _review()

    chat_started = time.monotonic()
    chat = await answer_review_question(
        review,
        ChatRequest(
            message="이 조항을 표준계약서 대비 검토 후보 관점에서 설명해 주세요.",
            focus_clause_id="uc_rev_llm_1",
        ),
        runtime=runtime,
        model=model,
        settings=settings,
    )
    chat_seconds = time.monotonic() - chat_started

    print(
        {
            "model": settings.llm_model,
            "provider": settings.llm_provider.value,
            "chat_outcome": chat.outcome,
            "chat_seconds": round(chat_seconds, 3),
            "raw_output": _serializable(model.outputs[0]),
        }
    )

    assert chat.outcome == "ANSWERED"
    assert chat.answer
    assert "0.95" not in chat.answer
    assert all(term not in chat.answer for term in ("일치", "적절", "문제없음", "안전"))
    assert chat.sources
    assert {source.id for source in chat.sources} <= {
        "uc_rev_llm_1",
        "std_liability_1",
        "law_1",
    }


async def test_real_llm_suggestion_structured_output() -> None:
    """Suggestions가 검증 가능한 표준조항·법령 ID를 포함해 생성한다."""
    settings = _settings()
    model = RecordingChatModel(create_chat_model(settings))
    runtime = SimpleNamespace(tools=(GroundingTool(),))
    review = _review()

    suggestion_started = time.monotonic()
    suggestion = await generate_suggestion(
        review,
        SuggestionRequest(
            user_clause_id="uc_rev_llm_1",
            purpose="손해배상 책임 범위를 명확히 표현",
            inputs={
                "responsibility_scope": ("귀책사유로 직접 발생한 손해에 대한 책임 범위")
            },
        ),
        runtime=runtime,
        model=model,
        settings=settings,
    )
    suggestion_seconds = time.monotonic() - suggestion_started

    print(
        {
            "model": settings.llm_model,
            "provider": settings.llm_provider.value,
            "suggestion_outcome": suggestion.outcome,
            "suggestion_seconds": round(suggestion_seconds, 3),
            "raw_output": _serializable(model.outputs[0]),
        }
    )

    assert suggestion.outcome == "GENERATED"
    assert suggestion.text
    assert suggestion.standard_clause_ids == ["std_liability_1"]
    assert suggestion.grounding_source_ids == ["law_1"]
