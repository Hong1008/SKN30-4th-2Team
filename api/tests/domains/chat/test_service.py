"""Chat의 단계별 근거 사용과 MCP 법령 조회 조건을 검증한다."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.domains.chat.schemas import ChatRequest
from app.domains.chat.service import answer_review_question
from app.domains.reviews.domain import MCPReviewStatus, Review, ReviewState


class GroundingTool:
    name = "get_category_grounding"

    def __init__(self, *, status: str = "OK") -> None:
        self.status = status
        self.calls: list[dict[str, object]] = []

    async def ainvoke(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(payload)
        response: dict[str, object] = {
            "status": self.status,
            "category": {"code": "LIABILITY", "label": "책임·손해배상"},
            "grounding": [],
        }
        if self.status == "OK":
            response["grounding"] = [
                {
                    "source_id": "law_1",
                    "law_name": "민법",
                    "article": "제390조",
                    "text": "채무불이행으로 인한 손해배상 참고 원문",
                }
            ]
        return response


class StructuredRunnable:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str) -> dict[str, object]:
        self.prompts.append(prompt)
        return self.payload


class ChatModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self.runnable = StructuredRunnable(payload)

    def with_structured_output(self, _schema: type) -> StructuredRunnable:
        return self.runnable


def _review() -> Review:
    now = datetime.now(UTC)
    return Review.restore(
        review_id="rev_chat",
        session_id="ses_chat",
        idempotency_key="chat-test",
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
                    "user_clause_id": "uc_rev_chat_1",
                    "user_clause": "손해배상 책임의 범위는 상호 협의한다.",
                    "deviation": "NONE",
                    "match": {
                        "status": "CANDIDATE_SELECTED",
                        "standard": {
                            "clause_id": "std_liability_1",
                            "category": "LIABILITY",
                            "title": "손해배상",
                            "text": "귀책사유가 있는 당사자는 손해를 배상한다.",
                        },
                    },
                    "toxic_patterns": [],
                }
            ],
            "missing_standard_clauses": [],
        },
        started_at=now,
        completed_at=now,
    )


def _settings() -> Settings:
    return Settings(app_env="local", llm_provider="ollama", llm_model="test")


@pytest.mark.asyncio
async def test_focused_question_uses_user_and_standard_when_law_is_unavailable() -> None:
    """법령 NO_RESULT여도 사용자·표준조항 설명은 ANSWERED로 유지한다."""
    tool = GroundingTool(status="NO_RESULT")
    model = ChatModel({
        "outcome": "ANSWERED",
        "answer": "사용자 조항은 책임 범위를 협의 대상으로 두고 있습니다.",
        "sources": [
            {"type": "USER_CLAUSE", "id": "uc_rev_chat_1"},
            {"type": "STANDARD_CLAUSE", "id": "std_liability_1"},
        ],
        "limitations": ["관련 법령 원문은 확인되지 않았습니다."],
    })

    response = await answer_review_question(
        _review(),
        ChatRequest(
            message="사용자 조항과 표준조항을 비교해줘.",
            focus_clause_id="uc_rev_chat_1",
        ),
        runtime=SimpleNamespace(tools=(tool,)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert response.tool_status == "NO_RESULT"
    assert {source.type for source in response.sources} == {
        "USER_CLAUSE",
        "STANDARD_CLAUSE",
    }
    assert tool.calls == [
        {"contract_type": "SW_FREELANCE", "category": "LIABILITY"}
    ]


@pytest.mark.asyncio
async def test_whole_review_law_question_fetches_current_review_category() -> None:
    """전체 질문도 법령을 명시하면 검토 결과 category로 MCP를 조회한다."""
    tool = GroundingTool()
    model = ChatModel({
        "outcome": "ANSWERED",
        "answer": "관련 법령 참고 원문과 함께 확인할 수 있습니다.",
        "sources": [{"type": "LAW", "id": "law_1"}],
        "limitations": [],
    })

    response = await answer_review_question(
        _review(),
        ChatRequest(message="이 검토 결과와 관련된 법령 근거를 알려줘."),
        runtime=SimpleNamespace(tools=(tool,)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert response.tool_status == "OK"
    assert tool.calls == [
        {"contract_type": "SW_FREELANCE", "category": "LIABILITY"}
    ]


@pytest.mark.asyncio
async def test_whole_review_plain_question_skips_law_lookup() -> None:
    """일반 요약 질문은 불필요한 MCP 법령 조회 없이 검토 결과로 답한다."""
    tool = GroundingTool()
    model = ChatModel({
        "outcome": "ANSWERED",
        "answer": "별도 확인이 필요한 검토 후보를 설명합니다.",
        "sources": [{"type": "USER_CLAUSE", "id": "uc_rev_chat_1"}],
        "limitations": [],
    })

    response = await answer_review_question(
        _review(),
        ChatRequest(message="별도 확인이 필요한 조항을 요약해줘."),
        runtime=SimpleNamespace(tools=(tool,)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert response.tool_status == "OK"
    assert tool.calls == []
