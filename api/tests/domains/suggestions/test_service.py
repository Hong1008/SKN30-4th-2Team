"""Suggestions의 LLM source key와 백엔드 출처 결합을 검증한다."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

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


@pytest.mark.asyncio
async def test_backend_binds_ids_from_source_keys_without_exposing_them_to_llm() -> None:
    """LLM은 논리 키만 선택하고 실제 출처 ID는 백엔드가 결합한다."""
    model = SourceKeyModel({
        "outcome": "GENERATED",
        "suggestion": "귀책사유로 직접 발생한 손해를 배상한다.",
        "major_changes": ["책임 범위를 귀책사유 기준으로 명확화"],
        "used_source_keys": ["SRC_USER", "SRC_STANDARD", "SRC_GROUNDING"],
        "required_confirmations": [],
    })
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
    model = SourceKeyModel({
        "outcome": "GENERATED",
        "suggestion": "귀책사유가 있는 당사자는 발생한 손해를 배상한다.",
        "major_changes": [],
        "used_source_keys": ["SRC_STANDARD"],
        "required_confirmations": [],
    })
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
