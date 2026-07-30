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
from app.domains.chat.schemas import ChatHistoryMessage, ChatRequest
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
                    "source_url": "https://www.law.go.kr/법령/민법/제390조",
                }
            ]
        return response


class StructuredRunnable:
    def __init__(
        self,
        payload: object,
        *,
        include_raw: bool = False,
        finish_reason: str = "stop",
    ) -> None:
        self.payload = payload
        self.include_raw = include_raw
        self.finish_reason = finish_reason
        self.prompts: list[list[object]] = []

    async def ainvoke(self, prompt: list[object]) -> object:
        self.prompts.append(prompt)
        if self.include_raw:
            return {
                "raw": SimpleNamespace(
                    response_metadata={"finish_reason": self.finish_reason},
                    usage_metadata={
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "total_tokens": 150,
                    },
                ),
                "parsed": self.payload,
                "parsing_error": None,
            }
        return self.payload


class ChatModel:
    def __init__(self, payload: object, *, finish_reason: str = "stop") -> None:
        self.payload = payload
        self.finish_reason = finish_reason
        self.runnable = StructuredRunnable(payload)

    def with_structured_output(
        self,
        _schema: type,
        *,
        include_raw: bool = False,
    ) -> StructuredRunnable:
        self.runnable.include_raw = include_raw
        self.runnable.finish_reason = self.finish_reason
        return self.runnable


class SequenceChatModel:
    def __init__(self, outputs: list[tuple[object, str]]) -> None:
        self.outputs = outputs
        self.runnables: list[StructuredRunnable] = []

    def with_structured_output(
        self,
        _schema: type,
        *,
        include_raw: bool = False,
    ) -> StructuredRunnable:
        payload, finish_reason = self.outputs[len(self.runnables)]
        runnable = StructuredRunnable(
            payload,
            include_raw=include_raw,
            finish_reason=finish_reason,
        )
        self.runnables.append(runnable)
        return runnable


class FailingChatModel:
    def with_structured_output(self, _schema: type, **_kwargs: object) -> None:
        raise ValueError("사용자 질문이나 비밀값이 포함될 수 있는 내부 메시지")


class RaisingRunnable:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def ainvoke(self, _prompt: list[object]) -> dict[str, object]:
        raise self.error


class RaisingChatModel:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def with_structured_output(
        self,
        _schema: type,
        **_kwargs: object,
    ) -> RaisingRunnable:
        return RaisingRunnable(self.error)


class SlowRunnable:
    async def ainvoke(self, _prompt: list[object]) -> dict[str, object]:
        await asyncio.sleep(0.1)
        return {}


class SlowChatModel:
    def with_structured_output(
        self,
        _schema: type,
        **_kwargs: object,
    ) -> SlowRunnable:
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


def _review_with_payment_clause() -> Review:
    review = _review()
    assert review.result is not None
    review.result["clause_results"].append(
        {
            "user_clause_id": "uc_rev_chat_2",
            "user_clause": "용역대금은 3,000,000원이며 매월 말일 지급한다.",
            "deviation": "NONE",
            "match": {
                "status": "CANDIDATE_SELECTED",
                "standard": {
                    "clause_id": "std_payment_1",
                    "category": "PAYMENT",
                    "title": "용역대금 지급",
                    "text": "용역대금과 지급기일은 당사자가 합의하여 정한다.",
                },
            },
            "toxic_patterns": [],
        }
    )
    return review


def _review_with_confidentiality_clause() -> Review:
    review = _review()
    assert review.result is not None
    review.result["clause_results"].append(
        {
            "user_clause_id": "uc_confidentiality_1",
            "user_clause": (
                "제5조 비밀유지\n계약 종료 후에도 업무상 비밀을 누설하지 않는다."
            ),
            "deviation": "EXTRA",
            "match": {
                "status": "CANDIDATE_SELECTED",
                "standard": {
                    "clause_id": "std_confidentiality_17",
                    "category": "CONFIDENTIALITY",
                    "title": "제17조 비밀준수",
                    "text": (
                        "제17조 비밀준수\n업무 종료 후 1년 동안 비밀을 준수한다. "
                        "제5조의 업무 범위도 비밀 대상에 포함한다."
                    ),
                },
            },
            "toxic_patterns": [],
        }
    )
    return review


def _review_with_scope_clauses() -> Review:
    review = _review()
    assert review.result is not None
    review.result["clause_results"] = [
        {
            "user_clause_id": "uc_rev_chat_1",
            "user_clause": (
                "## 제1조 (목적 및 업무 범위)\n"
                "을은 백엔드 API 개발, 데이터베이스 설계 및 API 명세서 "
                "작성을 수행하고 그 결과물을 납품한다."
            ),
            "deviation": "NONE",
            "match": {
                "status": "CANDIDATE_SELECTED",
                "standard": {
                    "clause_id": "std_scope_1",
                    "category": "SCOPE",
                    "title": "업무 범위",
                    "text": "### 제1조 (업무 범위)\n업무 범위는 별지에서 정한다.",
                },
            },
            "toxic_patterns": [],
        },
        {
            "user_clause_id": "uc_rev_chat_2",
            "user_clause": (
                "## 제2조 (계약기간 및 대금)\n"
                "계약기간은 2026년 7월 15일부터 2026년 8월 14일까지로 한다."
            ),
            "deviation": "NONE",
            "match": {
                "status": "CANDIDATE_SELECTED",
                "standard": {
                    "clause_id": "std_period_1",
                    "category": "PERIOD",
                    "title": "계약기간",
                    "text": (
                        "### 제2조 (계약기간)\n추가비용이나 자동 연장 업무는 "
                        "별도 합의한다."
                    ),
                },
            },
            "toxic_patterns": [],
        },
        {
            "user_clause_id": "uc_rev_chat_3",
            "user_clause": (
                "## 제3조 (검수 및 보완)\n"
                "추가 업무는 갑과 을의 별도 서면 합의로 정한다."
            ),
            "deviation": "NONE",
            "match": {"status": "NO_MATCH"},
            "toxic_patterns": [],
        },
        {
            "user_clause_id": "uc_rev_chat_4",
            "user_clause": (
                "## 제4조 (계약 해지)\n"
                "중대한 계약 위반을 시정하지 않으면 서면 통지로 해지할 수 있다."
            ),
            "deviation": "NONE",
            "match": {"status": "NO_MATCH"},
            "toxic_patterns": [],
        },
    ]
    review.result["missing_standard_clauses"] = [
        {
            "deviation": "MISSING",
            "standard": {
                "clause_id": "std_jurisdiction_22",
                "category": "JURISDICTION",
                "title": "관할 법원",
                "text": (
                    "### 제22조 (관할 법원)\n"
                    "분쟁은 민사소송법상 관할 법원에 제기한다."
                ),
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
            "answer": (
                "사용자 조항은 책임 범위를 협의 대상으로 두지만, 대응 표준조항은 "
                "귀책사유가 있는 당사자의 손해배상을 정하고 있습니다."
            ),
            "sources": [
                    {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                    {"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"},
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
            "sources": [
                {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                {"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"},
            ],
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
            "answer": "민법 제390조 참고 원문과 함께 확인할 수 있습니다.",
            "sources": [
                {
                    "type": "LAW",
                    "id": "SRC_LAW_1",
                    "source_url": "https://unverified.example/law",
                }
            ],
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
    assert response.sources[0].law_name == "민법"
    assert response.sources[0].article == "제390조"
    assert response.sources[0].source_url == (
        "https://www.law.go.kr/법령/민법/제390조"
    )


@pytest.mark.asyncio
async def test_verified_law_only_answer_does_not_invent_contract_clause() -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "민법 제390조는 채무불이행으로 인한 손해배상 근거를 다룹니다.",
            "sources": [{"type": "LAW", "id": "SRC_LAW_1"}],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(message="민법 제390조가 어떤 내용인지 설명해 줘."),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert [source.type for source in response.sources] == ["LAW"]
    assert response.limitations[-1] == (
        "현재 계약서 조항과의 직접 비교는 확인하지 못했습니다."
    )


@pytest.mark.asyncio
async def test_user_standard_and_law_sources_can_be_combined() -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": (
                "사용자 계약서는 책임 범위를 협의 대상으로 두고, 대응 표준조항은 "
                "귀책사유 기준을 제시합니다. 민법 제390조도 손해배상 근거를 다룹니다."
            ),
            "sources": [
                {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                {"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"},
                {"type": "LAW", "id": "SRC_LAW_1"},
            ],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(
            message="이 조항을 표준조항 및 법령 근거와 비교해 줘.",
            focus_clause_id="uc_rev_chat_1",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert {source.type for source in response.sources} == {
        "USER_CLAUSE",
        "STANDARD_CLAUSE",
        "LAW",
    }


@pytest.mark.asyncio
async def test_false_law_unavailable_limitation_is_regenerated_once() -> None:
    model = SequenceChatModel(
        [
            (
                {
                    "outcome": "ANSWERED",
                    "answer": "사용자 조항과 대응 표준조항을 비교합니다.",
                    "sources": [
                        {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                        {"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"},
                    ],
                    "limitations": ["법령 근거를 확인할 수 없습니다."],
                },
                "stop",
            ),
            (
                {
                    "outcome": "ANSWERED",
                    "answer": (
                        "사용자 조항과 대응 표준조항을 비교하고, 민법 제390조 "
                        "참고 원문을 함께 확인했습니다."
                    ),
                    "sources": [
                        {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                        {"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"},
                        {"type": "LAW", "id": "SRC_LAW_1"},
                    ],
                    "limitations": [],
                },
                "stop",
            ),
        ]
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(
            message="이 조항을 표준조항 및 법령 근거와 비교해 줘.",
            focus_clause_id="uc_rev_chat_1",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert len(model.runnables) == 2
    assert response.limitations == []
    assert {source.type for source in response.sources} == {
        "USER_CLAUSE",
        "STANDARD_CLAUSE",
        "LAW",
    }


@pytest.mark.asyncio
async def test_plain_question_does_not_fetch_law_grounding() -> None:
    """일반 설명 질문은 법령 MCP를 호출하지 않는다."""
    tool = GroundingTool()
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "별도 확인이 필요한 검토 후보를 설명합니다.",
            "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
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
            "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
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
    ("question", "answer", "uses_standard"),
    [
        (
            "이거 뭐가 문제야?",
            "사용자 조항은 책임 범위를 협의로 남겨 표준조항보다 기준이 불명확합니다.",
            True,
        ),
        (
            "회사에 뭐라고 말해?",
            "손해배상 책임의 발생 요건과 범위를 계약서에 구체적으로 정해 주시기 바랍니다.",
            False,
        ),
    ],
)
async def test_ambiguous_focused_question_uses_single_system_prompt_and_context(
    question: str,
    answer: str,
    uses_standard: bool,
) -> None:
    tool = GroundingTool()
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": answer,
            "sources": [
                {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                *(
                    [{"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"}]
                    if uses_standard
                    else []
                ),
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
    assert response.sources[1].standard_contract_label == (
        "SW 프리랜서 용역 표준계약서"
    )
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
async def test_standard_reference_has_exact_user_facing_standard_source() -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": (
                "대응 표준계약서 제17조 비밀준수에는 업무 종료 후 1년으로 "
                "기재되어 있습니다."
            ),
            "sources": [
                {"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"},
            ],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review_with_confidentiality_clause(),
        ChatRequest(
            message="비밀유지 기간을 표준조항과 비교해줘.",
            focus_clause_id="uc_confidentiality_1",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert {source.id for source in response.sources} == {
        "uc_confidentiality_1",
        "std_confidentiality_17",
    }
    standard_source = next(
        source for source in response.sources if source.type == "STANDARD_CLAUSE"
    )
    assert standard_source.display_label == (
        "SW 프리랜서 용역 표준계약서 · 제17조 비밀준수"
    )
    assert all("liability" not in (source.id or "") for source in response.sources)


@pytest.mark.asyncio
async def test_missing_standard_source_is_safely_supplemented() -> None:
    answer = "표준계약서 기준 제17조 비밀준수에는 종료 후 1년이 기재되어 있습니다."
    model = SequenceChatModel(
        [
            (
                {
                    "outcome": "ANSWERED",
                    "answer": answer,
                    "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
                    "limitations": [],
                },
                "stop",
            ),
            (
                {
                    "outcome": "ANSWERED",
                    "answer": answer,
                    "sources": [
                        {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                        {"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"},
                    ],
                    "limitations": [],
                },
                "stop",
            ),
        ]
    )

    response = await answer_review_question(
        _review_with_confidentiality_clause(),
        ChatRequest(
            message="비밀유지 기간을 표준조항과 비교해줘.",
            focus_clause_id="uc_confidentiality_1",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert len(model.runnables) == 1
    assert {source.id for source in response.sources} == {
        "uc_confidentiality_1",
        "std_confidentiality_17",
    }


@pytest.mark.asyncio
async def test_repeated_question_uses_same_deterministic_source_supplement() -> None:
    invalid = {
        "outcome": "ANSWERED",
        "answer": "표준계약서 기준 제17조 비밀준수에는 1년이 기재되어 있습니다.",
        "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
        "limitations": [],
    }
    model = SequenceChatModel([(invalid, "stop"), (invalid, "stop")])

    response = await answer_review_question(
        _review_with_confidentiality_clause(),
        ChatRequest(
            message="비밀유지 기간을 표준조항과 비교해줘.",
            focus_clause_id="uc_confidentiality_1",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert len(model.runnables) == 1
    assert {source.id for source in response.sources} == {
        "uc_confidentiality_1",
        "std_confidentiality_17",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "법률 지식 없는 사람도 이해할 수 있도록 제5조를 설명해 줘.",
        "계약서 제5조를 설명해 줘.",
        "비밀유지 의무가 계약 종료 후에도 적용되는지 설명해 줘.",
    ],
)
async def test_user_article_explanation_is_not_misread_as_standard_reference(
    question: str,
) -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": (
                "계약서 제5조는 계약 종료 후에도 업무상 비밀을 누설하지 "
                "않도록 정한 조항입니다."
            ),
            "sources": [],
            "limitations": [],
        }
    )

    review = _review_with_confidentiality_clause()
    first = await answer_review_question(
        review,
        ChatRequest(message=question, focus_clause_id="uc_confidentiality_1"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )
    second = await answer_review_question(
        review,
        ChatRequest(message=question, focus_clause_id="uc_confidentiality_1"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    for response in (first, second):
        assert response.outcome == "ANSWERED"
        assert [source.id for source in response.sources] == [
            "uc_confidentiality_1"
        ]
        assert all(source.type != "STANDARD_CLAUSE" for source in response.sources)


@pytest.mark.asyncio
async def test_standard_text_other_article_number_does_not_require_extra_source() -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": (
                "사용자 계약서 제5조에는 기간이 없고 대응 표준조항에는 "
                "업무 종료 후 1년으로 기재되어 있습니다."
            ),
            "sources": [],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review_with_confidentiality_clause(),
        ChatRequest(
            message="표준조항과 비교했을 때 빠진 내용과 추가된 내용을 알려 줘.",
            focus_clause_id="uc_confidentiality_1",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert {source.id for source in response.sources} == {
        "uc_confidentiality_1",
        "std_confidentiality_17",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_source",
    [
        {"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_99"},
        {"type": "STANDARD_CLAUSE", "id": "SRC_USER_1"},
        {"type": "LAW", "id": "SRC_LAW_99"},
    ],
)
async def test_structurally_invalid_source_remains_blocked(
    invalid_source: dict[str, str],
) -> None:
    invalid = {
        "outcome": "ANSWERED",
        "answer": "계약서 제5조의 비밀유지 의무를 설명합니다.",
        "sources": [invalid_source],
        "limitations": [],
    }
    model = SequenceChatModel([(invalid, "stop"), (invalid, "stop")])

    response = await answer_review_question(
        _review_with_confidentiality_clause(),
        ChatRequest(
            message="계약서 제5조를 설명해 줘.",
            focus_clause_id="uc_confidentiality_1",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "LLM_OUTPUT_INVALID"
    assert len(model.runnables) == 2


@pytest.mark.asyncio
async def test_whole_review_question_selects_matching_clause_and_hides_source_key() -> (
    None
):
    review = _review()
    assert review.result is not None
    review.result["clause_results"][0]["user_clause"] = (
        "하자가 있으면 을이 협의된 기간 내에 보완한다."
    )
    review.result["clause_results"].append(
        {
            "user_clause_id": "uc_rev_chat_2",
            "user_clause": "대금은 매월 말일 지급한다.",
            "deviation": "NONE",
            "match": {"status": "NO_MATCH"},
            "toxic_patterns": [],
        }
    )
    model = SequenceChatModel(
        [
            (
                {
                    "outcome": "ANSWERED",
                    "answer": "SRC_USER_1에 따르면 하자는 을이 보완합니다.",
                    "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
                    "limitations": [],
                },
                "stop",
            ),
            (
                {
                    "outcome": "ANSWERED",
                    "answer": "계약 조항에 따르면 하자는 을이 보완합니다.",
                    "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
                    "limitations": [],
                },
                "stop",
            ),
        ]
    )

    response = await answer_review_question(
        review,
        ChatRequest(message="하자가 있으면 누가 보완하나요?"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    messages = model.runnables[0].prompts[0]
    context = json.loads(str(messages[1].content).split("\n", 1)[1])
    assert len(context["review_result"]["clause_results"]) == 1
    assert "하자가" in context["review_result"]["clause_results"][0]["user_clause"]
    assert "SRC_" not in response.answer
    assert response.sources[0].id == "uc_rev_chat_1"


@pytest.mark.asyncio
async def test_short_follow_up_reuses_previous_user_question_context() -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "업무 범위가 넓어 책임 대상이 불명확할 수 있기 때문입니다.",
            "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review_with_scope_clauses(),
        ChatRequest(
            message="왜?",
            history=[
                ChatHistoryMessage(
                    role="user",
                    content="을의 업무 범위가 왜 불리한가요?",
                ),
                ChatHistoryMessage(
                    role="assistant",
                    content="업무 범위가 넓게 정해져 있습니다.",
                ),
            ],
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    context = json.loads(
        str(model.runnable.prompts[0][1].content).split("\n", 1)[1]
    )
    assert response.outcome == "ANSWERED"
    assert len(context["review_result"]["clause_results"]) == 1
    assert "백엔드 API 개발" in (
        context["review_result"]["clause_results"][0]["user_clause"]
    )


@pytest.mark.asyncio
async def test_backend_supplements_deterministic_user_source() -> None:
    answer = "손해배상 책임 범위는 상호 협의하도록 정해져 있습니다."
    model = SequenceChatModel(
        [
            (
                {
                    "outcome": "ANSWERED",
                    "answer": answer,
                    "sources": [],
                    "limitations": [],
                },
                "stop",
            ),
            (
                {
                    "outcome": "ANSWERED",
                    "answer": answer,
                    "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
                    "limitations": [],
                },
                "stop",
            ),
        ]
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(message="손해배상 책임 범위는 어떻게 정했나요?"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert len(model.runnables) == 1
    assert {source.id for source in response.sources} == {
        "uc_rev_chat_1",
    }


@pytest.mark.asyncio
async def test_particle_suffix_question_selects_only_payment_clause() -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "용역대금은 3,000,000원이고 매월 말일에 지급합니다.",
            "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review_with_payment_clause(),
        ChatRequest(message="용역대금은 얼마인가요?"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    context = json.loads(str(model.runnable.prompts[0][-1].content).split("\n", 1)[1])
    selected = context["review_result"]["clause_results"]
    assert len(selected) == 1
    assert "3,000,000원" in selected[0]["user_clause"]
    assert {source.id for source in response.sources} == {
        "uc_rev_chat_2",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "expected_ids", "expected_text"),
    [
        (
            "을의 업무 범위에는 무엇이 포함되나요?",
            {"uc_rev_chat_1"},
            "API 명세서",
        ),
        (
            "추가 업무가 발생했을 때 자동으로 을이 수행해야 하나요?",
            {"uc_rev_chat_2", "uc_rev_chat_3"},
            "별도 서면 합의",
        ),
    ],
)
async def test_clause_ranking_searches_user_and_standard_clause_text(
    question: str,
    expected_ids: set[str],
    expected_text: str,
) -> None:
    model_sources = [
        {"type": "USER_CLAUSE", "id": f"SRC_USER_{index}"}
        for index in range(1, len(expected_ids) + 1)
    ]
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "질문과 직접 관련된 사용자 계약서 문언을 확인했습니다.",
            "sources": model_sources,
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review_with_scope_clauses(),
        ChatRequest(message=question),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    context = json.loads(str(model.runnable.prompts[0][-1].content).split("\n", 1)[1])
    selected = context["review_result"]["clause_results"]
    assert any(expected_text in item["user_clause"] for item in selected)
    assert {source.id for source in response.sources} == expected_ids


@pytest.mark.asyncio
async def test_whole_review_risk_question_limits_candidates_to_requested_count() -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "확인된 조항 가운데 주의할 내용을 세 가지 범위에서 설명합니다.",
            "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review_with_scope_clauses(),
        ChatRequest(
            message="이 계약서에서 수급사업자에게 가장 불리한 조항 3개를 쉬운 말로 설명해 줘."
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    context = json.loads(str(model.runnable.prompts[0][-1].content).split("\n", 1)[1])
    selected_count = len(context["review_result"]["clause_results"]) + len(
        context["review_result"]["missing_standard_clauses"]
    )
    assert response.outcome == "ANSWERED"
    assert selected_count == 3
    assert len(response.sources) <= 6


@pytest.mark.asyncio
async def test_multiple_topics_returns_partial_answer_for_found_clauses() -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": "대금과 검수 관련 문구는 확인되지만 지연 책임 문구는 확인되지 않습니다.",
            "sources": [
                {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                {"type": "USER_CLAUSE", "id": "SRC_USER_2"},
            ],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review_with_scope_clauses(),
        ChatRequest(
            message="대금 지급, 검수, 지연 책임 조항 사이에 충돌하거나 모호한 부분이 있는지 찾아줘."
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert "지연 책임 항목은 현재 검토 결과에서 명확히 확인되지 않았습니다." == (
        response.limitations[-1]
    )
    assert response.answer and response.answer.startswith(
        "확인된 조항을 기준으로 설명합니다."
    )


@pytest.mark.asyncio
async def test_missing_standard_is_searched_separately_from_user_clauses() -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": (
                "사용자 계약서에는 특정 관할 법원이 없고, "
                "표준조항 후보는 법정 관할 법원을 제시합니다."
            ),
            "sources": [{"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"}],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review_with_scope_clauses(),
        ChatRequest(message="계약서에 정한 관할 법원은 어디인가요?"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    context = json.loads(str(model.runnable.prompts[0][-1].content).split("\n", 1)[1])
    assert context["review_result"]["clause_results"] == []
    assert len(context["review_result"]["missing_standard_clauses"]) == 1
    assert {source.id for source in response.sources} == {"std_jurisdiction_22"}
    assert response.sources[0].display_label == (
        "SW 프리랜서 용역 표준계약서 · 제22조 관할 법원"
    )


@pytest.mark.asyncio
async def test_false_insufficient_grounding_is_regenerated_once() -> None:
    model = SequenceChatModel(
        [
            (
                {
                    "outcome": "INSUFFICIENT_GROUNDING",
                    "answer": None,
                    "sources": [],
                    "limitations": ["근거가 없습니다."],
                },
                "stop",
            ),
            (
                {
                    "outcome": "ANSWERED",
                    "answer": (
                        "업무 범위에는 백엔드 API 개발, 데이터베이스 설계 및 "
                        "API 명세서 작성이 포함됩니다."
                    ),
                    "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
                    "limitations": [],
                },
                "stop",
            ),
        ]
    )

    response = await answer_review_question(
        _review_with_scope_clauses(),
        ChatRequest(message="을의 업무 범위에는 무엇이 포함되나요?"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert len(model.runnables) == 2
    assert "required_source_keys" in str(model.runnables[1].prompts[0][-1].content)
    assert response.sources[0].display_label == "제1조 목적 및 업무 범위"


@pytest.mark.asyncio
async def test_repeated_false_insufficient_grounding_is_output_invalid() -> None:
    insufficient = {
        "outcome": "INSUFFICIENT_GROUNDING",
        "answer": None,
        "sources": [],
        "limitations": ["근거가 없습니다."],
    }
    model = SequenceChatModel([(insufficient, "stop"), (insufficient, "stop")])

    response = await answer_review_question(
        _review_with_scope_clauses(),
        ChatRequest(message="을의 업무 범위에는 무엇이 포함되나요?"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "LLM_OUTPUT_INVALID"
    assert len(model.runnables) == 2


@pytest.mark.asyncio
async def test_backend_supplements_each_directly_matched_user_clause() -> None:
    model = ChatModel(
        {
            "outcome": "ANSWERED",
            "answer": (
                "2026년 8월 10일은 계약기간 중이지만, "
                "계약 위반과 서면 통지라는 해지 조건도 충족해야 합니다."
            ),
            "sources": [
                {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                {"type": "USER_CLAUSE", "id": "SRC_USER_2"},
            ],
            "limitations": [],
        }
    )

    response = await answer_review_question(
        _review_with_scope_clauses(),
        ChatRequest(message="계약 기간 중인 2026년 8월 10일에 계약 해지가 가능한가요?"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert {source.id for source in response.sources} == {
        "uc_rev_chat_2",
        "uc_rev_chat_4",
    }
    assert {source.display_label for source in response.sources} == {
        "제2조 계약기간 및 대금",
        "제4조 계약 해지",
    }


@pytest.mark.asyncio
async def test_incomplete_answer_is_regenerated_once() -> None:
    model = SequenceChatModel(
        [
            (
                {
                    "outcome": "ANSWERED",
                    "answer": "용역대금은 3,000,000원이며,",
                    "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
                    "limitations": [],
                },
                "stop",
            ),
            (
                {
                    "outcome": "ANSWERED",
                    "answer": "용역대금은 3,000,000원이며 매월 말일에 지급합니다.",
                    "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
                    "limitations": [],
                },
                "stop",
            ),
        ]
    )

    response = await answer_review_question(
        _review_with_payment_clause(),
        ChatRequest(message="용역대금은 얼마인가요?"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert response.answer == "용역대금은 3,000,000원이며 매월 말일에 지급합니다."
    assert len(model.runnables) == 2
    assert len(model.runnables[1].prompts[0]) == 3


@pytest.mark.asyncio
async def test_token_limit_finish_reason_triggers_regeneration() -> None:
    model = SequenceChatModel(
        [
            (
                {
                    "outcome": "ANSWERED",
                    "answer": "용역대금은 3,000,000원입니다.",
                    "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
                    "limitations": [],
                },
                "MAX_TOKENS",
            ),
            (
                {
                    "outcome": "ANSWERED",
                    "answer": "용역대금은 3,000,000원입니다.",
                    "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
                    "limitations": [],
                },
                "STOP",
            ),
        ]
    )

    response = await answer_review_question(
        _review_with_payment_clause(),
        ChatRequest(message="용역대금은 얼마인가요?"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert len(model.runnables) == 2


@pytest.mark.asyncio
async def test_repeated_incomplete_answer_is_output_invalid() -> None:
    incomplete = {
        "outcome": "ANSWERED",
        "answer": "용역대금은 3,000,000원이며,",
        "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
        "limitations": [],
    }
    model = SequenceChatModel([(incomplete, "stop"), (incomplete, "stop")])

    response = await answer_review_question(
        _review_with_payment_clause(),
        ChatRequest(message="용역대금은 얼마인가요?"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "LLM_OUTPUT_INVALID"
    assert response.answer is None
    assert len(model.runnables) == 2


@pytest.mark.asyncio
async def test_internal_terms_in_answer_or_limitations_are_repaired_once() -> None:
    model = SequenceChatModel(
        [
            (
                {
                    "outcome": "ANSWERED",
                    "answer": "review_result의 source_key를 확인했습니다.",
                    "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
                    "limitations": ["required_source_keys가 비어 있습니다."],
                },
                "stop",
            ),
            (
                {
                    "outcome": "ANSWERED",
                    "answer": "사용자 계약서 조항과 대응 표준조항을 비교했습니다.",
                    "sources": [
                        {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                        {"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"},
                    ],
                    "limitations": [],
                },
                "stop",
            ),
        ]
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(
            message="사용자 조항과 표준조항의 차이를 설명해줘.",
            focus_clause_id="uc_rev_chat_1",
        ),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert len(model.runnables) == 2
    assert "review_result" not in (response.answer or "")
    assert all("source_key" not in item for item in response.limitations)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_answer",
    [
        "이 표준조항은 사용자 계약서에 적용된다.",
        "이 조항이 적용될 가능성이 높다.",
        "이 사용자 조항은 법적으로 위법이다.",
        "원본 standard_contract_v2.md 경로를 참고했습니다.",
    ],
)
async def test_unsafe_legal_or_internal_file_expression_is_repaired_once(
    unsafe_answer: str,
) -> None:
    model = SequenceChatModel(
        [
            (
                {
                    "outcome": "ANSWERED",
                    "answer": unsafe_answer,
                    "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
                    "limitations": [],
                },
                "stop",
            ),
            (
                {
                    "outcome": "ANSWERED",
                    "answer": (
                        "사용자 계약서의 책임 범위 문구는 대응 표준조항과 차이가 "
                        "있으며 실제 적용 여부는 계약 전체 문구를 함께 확인해야 합니다."
                    ),
                    "sources": [
                        {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                        {"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"},
                    ],
                    "limitations": [],
                },
                "stop",
            ),
        ]
    )

    response = await answer_review_question(
        _review(),
        ChatRequest(message="책임 조항의 차이를 설명해줘.", focus_clause_id="uc_rev_chat_1"),
        runtime=SimpleNamespace(tools=(GroundingTool(),)),
        model=model,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert len(model.runnables) == 2
    assert ".md" not in (response.answer or "")
    assert "적용된다" not in (response.answer or "")
    assert "가능성이 높다" not in (response.answer or "")
    assert "위법이다" not in (response.answer or "")


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
            "sources": [
                {"type": "USER_CLAUSE", "id": "SRC_USER_1"},
                {"type": "STANDARD_CLAUSE", "id": "SRC_STANDARD_1"},
            ],
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
            "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
            "limitations": [],
        },
        {
            "outcome": "ANSWERED",
            "answer": "   \n\t",
            "sources": [{"type": "USER_CLAUSE", "id": "SRC_USER_1"}],
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
