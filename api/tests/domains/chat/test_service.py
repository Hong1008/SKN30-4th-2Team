"""Chat의 단계별 근거 사용과 MCP 법령 조회 조건을 검증한다."""

import logging
import json
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import Settings
from app.core.common.errors import ExternalServiceError, ExternalServiceTimeoutError
from app.core.llm.policy import LLMPolicy
from app.domains.chat.schemas import ChatRequest
from app.domains.chat.service import COMMON_SYSTEM_PROMPT, answer_review_question
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
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.prompts: list[list[object]] = []

    async def ainvoke(self, prompt: list[object]) -> object:
        self.prompts.append(prompt)
        return self.payload


class ChatModel:
    def __init__(self, payload: object) -> None:
        self.runnable = StructuredRunnable(payload)

    def with_structured_output(self, _schema: type) -> StructuredRunnable:
        return self.runnable


class FailingChatModel:
    def with_structured_output(self, _schema: type) -> None:
        raise ValueError("사용자 질문이나 비밀값이 포함될 수 있는 내부 메시지")


class RaisingRunnable:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def ainvoke(self, _prompt: list[object]) -> dict[str, object]:
        raise self.error


class RaisingChatModel:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def with_structured_output(self, _schema: type) -> RaisingRunnable:
        return RaisingRunnable(self.error)


class SlowRunnable:
    async def ainvoke(self, _prompt: list[object]) -> dict[str, object]:
        await asyncio.sleep(0.1)
        return {}


class SlowChatModel:
    def with_structured_output(self, _schema: type) -> SlowRunnable:
        return SlowRunnable()


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


def _review_with_missing_category() -> Review:
    review = _review()
    assert review.result is not None
    review.result["missing_standard_clauses"] = [
        {
            "deviation": "MISSING",
            "standard": {
                "clause_id": "std_payment_1",
                "category": "PAYMENT",
                "title": "대금 지급",
                "text": "대금은 정해진 기일에 지급한다.",
            },
        }
    ]
    return review


def _settings() -> Settings:
    return Settings(app_env="local", llm_provider="ollama", llm_model="test")


@pytest.mark.asyncio
async def test_focused_question_uses_user_and_standard_when_law_is_unavailable() -> (
    None
):
    """법령 NO_RESULT여도 사용자·표준조항 설명은 ANSWERED로 유지한다."""
    tool = GroundingTool(status="NO_RESULT")
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "사용자 조항은 책임 범위를 협의 대상으로 두고 있습니다.",
            "sources": [
                {"type": "USER_CLAUSE", "id": "uc_rev_chat_1"},
                {"type": "STANDARD_CLAUSE", "id": "std_liability_1"},
            ],
            "limitations": ["관련 법령 원문은 확인되지 않았습니다."],
        }
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(
            message="사용자 조항과 표준조항이 법적으로 어떻게 다른지 설명해줘.",
            focus_clause_id="uc_rev_chat_1",
        ),
        runtime=SimpleNamespace(tools=(tool,)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert response.tool_status == "NO_RESULT"
    assert "조회되지 않았습니다" in response.limitations[-1]
    assert {source.type for source in response.sources} == {
        "USER_CLAUSE",
        "STANDARD_CLAUSE",
    }
    assert tool.calls == [{"contract_type": "SW_FREELANCE", "category": "LIABILITY"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("TIMEOUT", "시간이 초과"),
        ("UPSTREAM_ERROR", "서비스 오류"),
    ],
)
async def test_chat_adds_deterministic_grounding_status_guidance(
    status: str,
    expected: str,
) -> None:
    tool = GroundingTool(status=status)
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "사용자 조항과 표준 대응 후보를 설명합니다.",
            "sources": [{"type": "USER_CLAUSE", "id": "uc_rev_chat_1"}],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(
            message="이 조항의 법적 근거를 설명해줘.",
            focus_clause_id="uc_rev_chat_1",
        ),
        runtime=SimpleNamespace(tools=(tool,)),
        model=model,
        settings=_settings(),
    )

    assert response.tool_status == status
    assert expected in response.limitations[-1]


@pytest.mark.asyncio
async def test_whole_review_law_question_fetches_current_review_category() -> None:
    """전체 질문도 법령을 명시하면 검토 결과 category로 MCP를 조회한다."""
    tool = GroundingTool()
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "관련 법령 참고 원문과 함께 확인할 수 있습니다.",
            "sources": [{"type": "LAW", "id": "law_1"}],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(message="이 검토 결과와 관련된 법령 근거를 알려줘."),
        runtime=SimpleNamespace(tools=(tool,)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert response.tool_status == "OK"
    assert tool.calls == [{"contract_type": "SW_FREELANCE", "category": "LIABILITY"}]


@pytest.mark.asyncio
async def test_plain_question_does_not_fetch_law_grounding() -> None:
    """일반 설명 질문은 법령 MCP를 호출하지 않는다."""
    tool = GroundingTool()
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "별도 확인이 필요한 검토 후보를 설명합니다.",
            "sources": [{"type": "USER_CLAUSE", "id": "uc_rev_chat_1"}],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(message="별도 확인이 필요한 조항을 요약해줘."),
        runtime=SimpleNamespace(tools=(tool,)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert response.tool_status == "NOT_REQUESTED"
    assert tool.calls == []
    assert {source.type for source in response.sources} == {"USER_CLAUSE"}


@pytest.mark.asyncio
async def test_whole_review_includes_missing_standard_clause_category() -> None:
    """누락 표준조항 후보의 category도 전체 검토 법령 조회에 포함한다."""
    tool = GroundingTool()
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "검토 후보를 설명합니다.",
            "sources": [{"type": "USER_CLAUSE", "id": "uc_rev_chat_1"}],
            "limitations": [],
        }
    )

    await answer_review_question(
        _review_with_missing_category(),
        ChatRequest(message="전체 결과와 관련된 법령 조문을 알려줘."),
        runtime=SimpleNamespace(tools=(tool,)),
        model=model,
        settings=_settings(),
    )

    assert tool.calls == [
        {"contract_type": "SW_FREELANCE", "category": "LIABILITY"},
        {"contract_type": "SW_FREELANCE", "category": "PAYMENT"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "answer"),
    [
        (
            "이거 뭐가 문제야?",
            "사용자 조항은 책임 범위를 협의로 남겨 표준조항보다 기준이 불명확합니다.",
        ),
        (
            "회사에 뭐라고 말해?",
            "손해배상 책임의 발생 요건과 범위를 계약서에 구체적으로 정해 주시기 바랍니다.",
        ),
    ],
)
async def test_ambiguous_focused_question_uses_single_system_prompt_and_context(
    question: str,
    answer: str,
) -> None:
    tool = GroundingTool()
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": answer,
            "sources": [
                {"type": "USER_CLAUSE", "id": "uc_rev_chat_1"},
                {"type": "STANDARD_CLAUSE", "id": "std_liability_1"},
            ],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(message=question, focus_clause_id="uc_rev_chat_1"),
        runtime=SimpleNamespace(tools=(tool,)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert response.answer == answer
    assert response.tool_status == "NOT_REQUESTED"
    assert tool.calls == []
    messages = model.runnable.prompts[0]
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == COMMON_SYSTEM_PROMPT
    assert isinstance(messages[1], HumanMessage)
    context = json.loads(str(messages[1].content).split("\n", 1)[1])
    assert context["review_id"] == "rev_chat"
    assert context["current_clause_id"] == "uc_rev_chat_1"
    assert context["current_clause_context"]["user_clause"]
    assert context["current_clause_context"]["match"]["standard"]["text"]
    assert context["current_clause_context"]["deviation"] == "NONE"


@pytest.mark.asyncio
async def test_backend_resolves_compact_source_keys_to_actual_ids() -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "계약 조항과 표준 대응 후보를 함께 확인했습니다.",
            "sources": [
                {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                {"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"},
            ],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(message="이거 설명해줘.", focus_clause_id="uc_rev_chat_1"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert [source.id for source in response.sources] == [
        "uc_rev_chat_1",
        "std_liability_1",
    ]
    messages = model.runnable.prompts[0]
    context = json.loads(str(messages[1].content).split("\n", 1)[1])
    assert context["current_clause_context"]["source_key"] == "SRC_USER_1"
    assert (
        context["current_clause_context"]["match"]["standard"]["source_key"]
        == "SRC_STANDARD_1"
    )
    assert "user_clause_id" not in context["current_clause_context"]
    assert "clause_id" not in context["current_clause_context"]["match"]["standard"]


@pytest.mark.asyncio
async def test_whole_review_question_selects_matching_clause_and_hides_source_key() -> (
    None
):
    review = _review()
    assert review.result is not None
    review.result["clause_results"][0][
        "user_clause"
    ] = "하자가 있으면 을이 협의된 기간 내에 보완한다."
    review.result["clause_results"].append(
        {
            "user_clause_id": "uc_rev_chat_2",
            "user_clause": "대금은 매월 말일 지급한다.",
            "deviation": "NONE",
            "match": {"status": "NO_MATCH"},
            "toxic_patterns": [],
        }
    )
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "SRC_USER_1에 따르면 하자는 을이 보완합니다.",
            "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        review,
        ChatRequest(message="하자가 있으면 누가 보완하나요?"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    messages = model.runnable.prompts[0]
    context = json.loads(str(messages[1].content).split("\n", 1)[1])
    assert len(context["review_result"]["clause_results"]) == 1
    assert "하자가" in context["review_result"]["clause_results"][0]["user_clause"]
    assert "SRC_" not in response.answer
    assert response.sources[0].id == "uc_rev_chat_1"


@pytest.mark.asyncio
async def test_backend_attaches_selected_sources_when_model_omits_them() -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "하자는 계약 문언에 따라 을이 협의된 기간 안에 보완합니다.",
            "sources": [],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(message="하자가 있으면 누가 보완하나요?"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert {source.id for source in response.sources} == {
        "uc_rev_chat_1",
        "std_liability_1",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["NO_RESULT", "TIMEOUT"])
async def test_legal_grounding_failure_still_calls_llm_with_clause_context(
    status: str,
) -> None:
    tool = GroundingTool(status=status)
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "조항 문언과 표준 대응 후보를 기준으로는 책임 범위를 더 구체화할 필요가 있습니다.",
            "sources": [{"type": "USER_CLAUSE", "id": "uc_rev_chat_1"}],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(message="법적으로 괜찮아?", focus_clause_id="uc_rev_chat_1"),
        runtime=SimpleNamespace(tools=(tool,)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert response.tool_status == status
    assert tool.calls == [{"contract_type": "SW_FREELANCE", "category": "LIABILITY"}]
    assert model.runnable.prompts
    assert response.limitations


@pytest.mark.asyncio
async def test_all_grounding_absent_limits_answer_without_llm_call() -> None:
    review = _review()
    assert review.result is not None
    review.result["clause_results"] = []
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "호출되면 안 됩니다.",
            "sources": [],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        review,
        ChatRequest(message="설명해줘."),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "INSUFFICIENT_GROUNDING"
    assert response.tool_status == "NOT_REQUESTED"
    assert model.runnable.prompts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_output",
    [
        "",
        "   \n\t",
        {
            "outcome": "ANSWERED",
            "answer": "",
            "sources": [{"type": "USER_CLAUSE", "id": "uc_rev_chat_1"}],
            "limitations": [],
        },
        {
            "outcome": "ANSWERED",
            "answer": "   \n\t",
            "sources": [{"type": "USER_CLAUSE", "id": "uc_rev_chat_1"}],
            "limitations": [],
        },
    ],
)
async def test_blank_llm_output_is_output_invalid(model_output: object) -> None:
    model = ChatModel(model_output)

    response = await answer_review_question(
        _review(),
        ChatRequest(message="이거 설명해줘.", focus_clause_id="uc_rev_chat_1"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "LLM_OUTPUT_INVALID"
    assert response.answer is None
    assert response.refused is True


def test_common_system_prompt_contains_required_context_rules() -> None:
    for required_rule in (
        "사용자 질문만 보지 말고",
        '"이거"',
        '"뭐가 문제야?"',
        '"회사에 뭐라고 말해?"',
        "협의문구 요청에는 설명만 하지 말고",
        "제공되지 않은 계약 내용이나 법령을 만들지 마세요",
        "법령 근거가 없더라도",
        "법률적 확정 판단이 어려우면",
        "모두 없을 때만 INSUFFICIENT_GROUNDING",
        "이해하기 쉬운 한국어로 핵심부터",
    ):
        assert required_rule in COMMON_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_llm_timeout_is_distinct_error() -> None:
    with pytest.raises(ExternalServiceTimeoutError) as caught:
        await answer_review_question(
            _review(),
            ChatRequest(message="이거 설명해줘.", focus_clause_id="uc_rev_chat_1"),
            runtime=SimpleNamespace(tools=(GroundingTool(),)),
            model=SlowChatModel(),
            settings=_settings(),
            llm_policy=LLMPolicy(timeout_seconds=0.01),
        )

    assert caught.value.code == "LLM_TIMEOUT"


@pytest.mark.asyncio
async def test_llm_connection_failure_is_distinct_error() -> None:
    with pytest.raises(ExternalServiceError) as caught:
        await answer_review_question(
            _review(),
            ChatRequest(message="이거 설명해줘.", focus_clause_id="uc_rev_chat_1"),
            runtime=SimpleNamespace(tools=(GroundingTool(),)),
            model=RaisingChatModel(ConnectionError("connection refused")),
            settings=_settings(),
        )

    assert caught.value.code == "LLM_CONNECTION_FAILED"


@pytest.mark.asyncio
async def test_logs_chat_generation_exception_without_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="uvicorn.error")

    response = await answer_review_question(
        _review(),
        ChatRequest(message="검토 결과를 설명해줘."),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=FailingChatModel(),
        settings=_settings(),
    )

    assert response.outcome == "LLM_OUTPUT_INVALID"
    assert "event=llm.chat.invalid_output" in caplog.text
    assert "review_id=rev_chat" in caplog.text
    assert "reason=STRUCTURED_OUTPUT_INVOCATION_FAILED" in caplog.text
    assert "error_type=ValueError" in caplog.text
    assert "사용자 질문" not in caplog.text
