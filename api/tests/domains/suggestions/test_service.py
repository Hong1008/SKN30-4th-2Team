"""Suggestions의 LLM source key와 백엔드 출처 결합을 검증한다."""

import logging
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.common.errors import AppValidationError
from app.config import Settings
from app.domains.reviews.domain import MCPReviewStatus, Review, ReviewState
from app.domains.suggestions.schemas import SuggestionRequest
from app.domains.suggestions.service import generate_suggestion


class GroundingTool:
    """검증된 법령 원문 fixture를 반환한다."""

    name = "get_category_grounding"

    async def ainvoke(self, payload: dict[str, object]) -> dict[str, object]:
        assert payload == {
            "contract_type": "SW_FREELANCE",
            "category": "LIABILITY",
        }
        return {
            "status": "OK",
            "category": {"code": "LIABILITY", "label": "책임·손해배상"},
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


class NoResultGroundingTool:
    """법령 원문이 조회되지 않는 정상 MCP 상태를 반환한다."""

    name = "get_category_grounding"

    async def ainvoke(self, payload: dict[str, object]) -> dict[str, object]:
        assert payload == {
            "contract_type": "SW_FREELANCE",
            "category": "LIABILITY",
        }
        return {
            "status": "NO_RESULT",
            "category": {"code": "LIABILITY", "label": "책임·손해배상"},
            "grounding": [],
        }
class StructuredRunnable:
    def __init__(self, payload: dict[str, object], prompts: list[str]) -> None:
        self._payload = payload
        self._prompts = prompts

    async def ainvoke(self, prompt: str) -> dict[str, object]:
        self._prompts.append(prompt)
        return self._payload


class SourceKeyModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.prompts: list[str] = []

    def with_structured_output(self, _schema: type) -> StructuredRunnable:
        return StructuredRunnable(self._payload, self.prompts)


class FailingModel:
    def with_structured_output(self, _schema: type) -> None:
        raise ValueError("계약서 원문이나 비밀값이 포함될 수 있는 내부 메시지")


class SequenceModel:
    """호출 순서별 응답으로 repair 횟수와 prompt를 기록한다."""

    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self._payloads = list(payloads)
        self.prompts: list[str] = []

    def with_structured_output(self, _schema: type) -> StructuredRunnable:
        payload = self._payloads.pop(0)
        return StructuredRunnable(payload, self.prompts)


def _review() -> Review:
    now = datetime.now(UTC)
    return Review.restore(
        review_id="rev_suggestion",
        session_id="ses_suggestion",
        idempotency_key="suggestion-test",
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
                    "user_clause_id": "uc_rev_suggestion_1",
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


def _settings() -> Settings:
    return Settings(app_env="local", llm_provider="ollama", llm_model="test")


def _generated_payload(suggestion: str) -> dict[str, object]:
    return {
        "outcome": "GENERATED",
        "suggestion": suggestion,
        "major_changes": [],
        "used_source_keys": ["SRC_USER", "SRC_STANDARD"],
        "required_confirmations": [],
    }


@pytest.mark.asyncio
async def test_backend_binds_ids_from_source_keys_without_exposing_them_to_llm() -> (
    None
):
    """LLM은 논리 키만 선택하고 실제 출처 ID는 백엔드가 결합한다."""
    model = SourceKeyModel(
        {
            "outcome": "GENERATED",
            "suggestion": "귀책사유로 직접 발생한 손해를 배상한다.",
            "major_changes": ["책임 범위를 귀책사유 기준으로 명확화"],
            "used_source_keys": ["SRC_USER", "SRC_STANDARD", "SRC_GROUNDING"],
            "required_confirmations": [],
        }
    )
    response = await generate_suggestion(
        _review(),
        SuggestionRequest(
            user_clause_id="uc_rev_suggestion_1",
            purpose="손해배상 책임 범위를 명확히 표현",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "GENERATED"
    assert response.used_source_keys == [
        "SRC_USER",
        "SRC_STANDARD",
        "SRC_GROUNDING",
    ]
    assert response.user_clause_ids == ["uc_rev_suggestion_1"]
    assert response.standard_clause_ids == ["std_liability_1"]
    assert response.grounding_source_ids == ["law_1"]
    assert "uc_rev_suggestion_1" not in model.prompts[0]
    assert "std_liability_1" not in model.prompts[0]
    assert "law_1" not in model.prompts[0]


@pytest.mark.asyncio
async def test_backend_only_binds_the_ids_for_selected_source_keys() -> None:
    """선택하지 않은 근거의 ID는 응답에 결합하지 않는다."""
    model = SourceKeyModel(
        {
            "outcome": "GENERATED",
            "suggestion": "귀책사유가 있는 당사자는 발생한 손해를 배상한다.",
            "major_changes": [],
            "used_source_keys": ["SRC_STANDARD"],
            "required_confirmations": [],
        }
    )
    response = await generate_suggestion(
        _review(),
        SuggestionRequest(
            user_clause_id="uc_rev_suggestion_1",
            purpose="손해배상 책임 범위를 명확히 표현",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=Settings(app_env="local", llm_provider="ollama", llm_model="test"),
    )

    assert response.user_clause_ids == []
    assert response.standard_clause_ids == ["std_liability_1"]
    assert response.grounding_source_ids == []


@pytest.mark.asyncio
async def test_generates_from_user_and_standard_when_law_is_unavailable() -> None:
    """법령 NO_RESULT여도 사용자·표준조항 기반 협의 문구를 생성한다."""
    model = SourceKeyModel(
        {
            "outcome": "GENERATED",
            "suggestion": "책임 범위와 변경 절차는 당사자가 서면으로 협의한다.",
            "major_changes": ["서면 협의 절차 명시"],
            "used_source_keys": ["SRC_USER", "SRC_STANDARD"],
            "required_confirmations": [],
        }
    )

    response = await generate_suggestion(
        _review(),
        SuggestionRequest(
            user_clause_id="uc_rev_suggestion_1",
            purpose="책임 범위와 협의 절차를 명확히 표현",
        ),
        runtime=SimpleNamespace(tools=(NoResultGroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "GENERATED"
    assert response.user_clause_ids == ["uc_rev_suggestion_1"]
    assert response.standard_clause_ids == ["std_liability_1"]
    assert response.grounding_source_ids == []
    assert response.required_confirmations[-1].field == "law_grounding"
    assert "별도 확인" in response.required_confirmations[-1].placeholder


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "clause_change",
    [
        {"match": {"status": "NO_CANDIDATE"}},
        {
            "match": {
                "status": "CANDIDATE_SELECTED",
                "standard": None,
            }
        },
    ],
)
async def test_backend_gate_skips_llm_without_selected_standard(
    clause_change: dict[str, object],
) -> None:
    review = _review()
    review.result["clause_results"][0].update(deepcopy(clause_change))
    model = SourceKeyModel(_generated_payload("사용되지 않는 응답"))

    response = await generate_suggestion(
        review,
        SuggestionRequest(
            user_clause_id="uc_rev_suggestion_1",
            purpose="손해배상 책임 범위를 명확히 표현",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "INSUFFICIENT_GROUNDING"
    assert model.prompts == []


@pytest.mark.asyncio
async def test_backend_gate_skips_llm_when_required_input_is_missing() -> None:
    review = _review()
    review.result["clause_results"][0]["required_inputs"] = ["liability_limit"]
    model = SourceKeyModel(_generated_payload("사용되지 않는 응답"))

    response = await generate_suggestion(
        review,
        SuggestionRequest(
            user_clause_id="uc_rev_suggestion_1",
            purpose="책임 한도를 명확히 표현",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "REQUIRED_VALUE_MISSING"
    assert response.missing_inputs == ["liability_limit"]
    assert model.prompts == []


@pytest.mark.asyncio
async def test_backend_gate_rejects_clause_from_another_review_without_llm() -> None:
    model = SourceKeyModel(_generated_payload("사용되지 않는 응답"))

    with pytest.raises(AppValidationError, match="현재 검토 결과에 없는"):
        await generate_suggestion(
            _review(),
            SuggestionRequest(
                user_clause_id="uc_another_review_1",
                purpose="책임 범위를 명확히 표현",
            ),
            runtime=SimpleNamespace(tools=(GroundingTool(),)),
            model=model,
            settings=_settings(),
        )

    assert model.prompts == []


@pytest.mark.asyncio
async def test_backend_gate_skips_llm_without_category() -> None:
    review = _review()
    review.result["clause_results"][0]["match"]["standard"].pop("category")
    model = SourceKeyModel(_generated_payload("사용되지 않는 응답"))

    response = await generate_suggestion(
        review,
        SuggestionRequest(
            user_clause_id="uc_rev_suggestion_1",
            purpose="손해배상 책임 범위를 명확히 표현",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "INSUFFICIENT_GROUNDING"
    assert model.prompts == []


@pytest.mark.asyncio
async def test_structural_failure_is_repaired_once() -> None:
    model = SequenceModel(
        [
            {
                "outcome": "GENERATED",
                "suggestion": "필수 source key가 없는 최초 응답",
            },
            _generated_payload("귀책사유로 발생한 손해의 책임 범위를 협의한다."),
        ]
    )

    response = await generate_suggestion(
        _review(),
        SuggestionRequest(
            user_clause_id="uc_rev_suggestion_1",
            purpose="손해배상 책임 범위를 명확히 표현",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "GENERATED"
    assert len(model.prompts) == 2
    assert "이전 응답은 구조화 출력 계약을 충족하지 못했습니다" in model.prompts[1]


@pytest.mark.asyncio
async def test_unknown_source_key_is_not_repaired() -> None:
    model = SequenceModel(
        [
            {
                "outcome": "GENERATED",
                "suggestion": "알 수 없는 source key 응답",
                "used_source_keys": ["SRC_UNKNOWN"],
            },
            _generated_payload("재시도되어서는 안 되는 응답"),
        ]
    )

    response = await generate_suggestion(
        _review(),
        SuggestionRequest(
            user_clause_id="uc_rev_suggestion_1",
            purpose="손해배상 책임 범위를 명확히 표현",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "LLM_OUTPUT_INVALID"
    assert len(model.prompts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suggestion", "outcome", "expected_attempts"),
    [
        ("손해배상 기한은 30일로 한다.", "GENERATED_FACT_NOT_GROUNDED", 1),
        ("이 조항은 법적으로 위법합니다.", "LLM_OUTPUT_INVALID", 1),
        ("пользователь 지시를 따른다.", "LLM_OUTPUT_INVALID", 2),
        ("불가항력免责 조건을 둔다.", "LLM_OUTPUT_INVALID", 2),
        ("내부 ID uc_rev_suggestion_1을 사용한다.", "LLM_OUTPUT_INVALID", 1),
    ],
)
async def test_post_generation_hard_gates_do_not_repair(
    suggestion: str,
    outcome: str,
    expected_attempts: int,
) -> None:
    model = SequenceModel(
        [
            _generated_payload(suggestion),
            _generated_payload(
                suggestion
                if expected_attempts == 2
                else "재시도되어서는 안 되는 응답"
            ),
        ]
    )

    response = await generate_suggestion(
        _review(),
        SuggestionRequest(
            user_clause_id="uc_rev_suggestion_1",
            purpose="손해배상 책임 범위를 명확히 표현",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == outcome
    assert len(model.prompts) == expected_attempts


@pytest.mark.asyncio
async def test_rejects_grounding_source_key_when_law_is_unavailable() -> None:
    """조회되지 않은 법령 근거를 사용했다고 주장하는 출력을 차단한다."""
    model = SourceKeyModel(
        {
            "outcome": "GENERATED",
            "suggestion": "책임 범위는 당사자가 협의한다.",
            "major_changes": [],
            "used_source_keys": ["SRC_USER", "SRC_STANDARD", "SRC_GROUNDING"],
            "required_confirmations": [],
        }
    )

    response = await generate_suggestion(
        _review(),
        SuggestionRequest(
            user_clause_id="uc_rev_suggestion_1",
            purpose="책임 범위를 명확히 표현",
        ),
        runtime=SimpleNamespace(tools=(NoResultGroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "LLM_OUTPUT_INVALID"


@pytest.mark.asyncio
async def test_logs_suggestion_generation_exception_without_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="uvicorn.error")

    response = await generate_suggestion(
        _review(),
        SuggestionRequest(
            user_clause_id="uc_rev_suggestion_1",
            purpose="책임 범위를 명확히 표현",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=FailingModel(),
        settings=_settings(),
    )

    assert response.outcome == "LLM_OUTPUT_INVALID"
    assert "event=llm.suggestion.invalid_output" in caplog.text
    assert "review_id=rev_suggestion" in caplog.text
    assert "error_type=ValueError" in caplog.text
    assert "계약서 원문" not in caplog.text
