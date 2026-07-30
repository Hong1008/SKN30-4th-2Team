"""LangGraph 질문 분류와 근거 제한을 검증한다."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from app.config import Settings
from app.core.common.errors import (
    AppValidationError,
    ConflictError,
    ExternalServiceTimeoutError,
)
from app.core.llm.policy import LLMPolicy
from app.domains.chat.schemas import ChatRequest
from app.domains.chat.service import (
    MAX_CONTEXT_CHARS,
    QuestionCategory,
    answer_review_question,
)
from app.domains.reviews.domain import MCPReviewStatus, Review, ReviewState


class Tool:
    def __init__(self, name: str, payload: dict[str, object]) -> None:
        self.name, self.payload, self.calls = name, payload, []

    async def ainvoke(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(payload)
        return self.payload


class Model:
    def __init__(self, *answers: str) -> None:
        self.answers, self.prompts = list(answers), []

    async def ainvoke(self, prompt: list[object]) -> AIMessage:
        self.prompts.append(prompt)
        return AIMessage(content=self.answers.pop(0))


class SlowModel:
    async def ainvoke(self, _prompt: list[object]) -> AIMessage:
        await asyncio.sleep(0.1)
        return AIMessage(content="늦은 답변")


def _review() -> Review:
    now = datetime.now(UTC)
    return Review.restore(
        review_id="rev_chat",
        session_id="ses_chat",
        idempotency_key="chat",
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
                    "user_clause_id": "uc_scope",
                    "user_clause": "제1조 업무 범위는 API 개발로 한다.",
                    "deviation": "NONE",
                    "toxic_patterns": [],
                    "match": {
                        "status": "CANDIDATE_SELECTED",
                        "standard": {
                            "clause_id": "std_scope",
                            "category": "SCOPE_SOW",
                            "title": "제1조 업무 범위",
                            "text": "업무 범위는 별지에서 구체적으로 정한다.",
                        },
                    },
                },
                {
                    "user_clause_id": "uc_change",
                    "user_clause": "제2조 갑은 업무 내용을 필요에 따라 변경할 수 있다.",
                    "deviation": "EXTRA",
                    "toxic_patterns": ["UNILATERAL_CHANGE"],
                    "match": {"status": "NO_CANDIDATE"},
                },
            ],
            "missing_standard_clauses": [
                {
                    "deviation": "MISSING",
                    "standard": {
                        "category": "PAYMENT",
                        "title": "대금 지급",
                        "text": "대금 지급 기준을 정한다.",
                    },
                }
            ],
        },
        started_at=now,
        completed_at=now,
    )


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(
        tools=(
            Tool(
                "list_categories",
                {
                    "categories": [
                        {"value": "SCOPE_SOW", "description": "과업범위 / 담당업무"}
                    ]
                },
            ),
            Tool(
                "list_toxic_pattern_details",
                {
                    "patterns": [
                        {
                            "pattern": "UNILATERAL_CHANGE",
                            "title": "일방적인 과업 범위 변경 권한",
                        }
                    ]
                },
            ),
            Tool(
                "get_category_grounding",
                {
                    "status": "OK",
                    "category": {"label": "과업범위 / 담당업무"},
                    "grounding": [
                        {
                            "source_id": "law_1",
                            "law_name": "민법",
                            "article": "제390조",
                            "text": "손해배상 참고 원문",
                        }
                    ],
                },
            ),
        )
    )


def _settings() -> Settings:
    return Settings(app_env="local", llm_provider="ollama", llm_model="test")


@pytest.mark.asyncio
async def test_classification_route_uses_labels_and_skips_law_mcp() -> None:
    runtime = _runtime()
    model = Model(
        QuestionCategory.CLASSIFICATION,
        "주의 신호는 일방적인 과업 범위 변경 권한과 유사한 문구를 뜻합니다.",
    )
    response = await answer_review_question(
        _review(),
        ChatRequest(
            message="주의 신호는 무엇을 뜻하나요?",
            history=[{"role": "user", "content": "별도 확인 조항은 무엇인가요?"}],
        ),
        runtime=runtime,
        router_model=model,
        model=model,
        settings=_settings(),
    )
    prompt = str(model.prompts[1][0].content)
    assert response.outcome == "ANSWERED"
    assert "검토 분류 질문" in prompt and "별도 확인 조항" in prompt
    assert "별도 확인 필요" in prompt and "일방적인 과업 범위 변경 권한" in prompt
    assert "EXTRA" not in prompt and "UNILATERAL_CHANGE" not in prompt
    assert (
        len(prompt.split("<검색된 문서>:\n", 1)[1].split("\n\n사용자 질문:", 1)[0])
        <= MAX_CONTEXT_CHARS
    )
    assert not runtime.tools[2].calls


@pytest.mark.asyncio
async def test_legal_route_fetches_grounding_only_for_review_categories() -> None:
    runtime = _runtime()
    model = Model(
        QuestionCategory.LEGAL_GROUNDING, "민법 제390조가 참고자료로 제공되었습니다."
    )
    response = await answer_review_question(
        _review(),
        ChatRequest(
            message="제1조의 법령 근거는 무엇인가요?", focus_clause_id="uc_scope"
        ),
        runtime=runtime,
        router_model=model,
        model=model,
        settings=_settings(),
    )
    assert response.outcome == "ANSWERED"
    assert "민법 제390조 손해배상 참고 원문" in str(model.prompts[1][0].content)
    assert runtime.tools[2].calls == [
        {"contract_type": "SW_FREELANCE", "category": "SCOPE_SOW"}
    ]


@pytest.mark.asyncio
async def test_clause_route_includes_focused_clause_and_standard_candidate() -> None:
    model = Model(
        QuestionCategory.CLAUSE, "제1조와 표준조항 후보의 업무 범위 표현이 다릅니다."
    )
    response = await answer_review_question(
        _review(),
        ChatRequest(message="이 조항을 설명해줘.", focus_clause_id="uc_scope"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )
    prompt = str(model.prompts[1][0].content)
    assert "제1조 업무 범위는 API 개발로 한다." in prompt
    assert "업무 범위는 별지에서 구체적으로 정한다." in prompt
    assert [(source.type, source.id) for source in response.sources] == [
        ("USER_CLAUSE", "uc_scope")
    ]


@pytest.mark.asyncio
async def test_review_result_keeps_missing_candidates_separate() -> None:
    model = Model(
        QuestionCategory.REVIEW_RESULT,
        "조항 검토 결과와 표준조항 누락 후보가 있습니다.",
    )
    response = await answer_review_question(
        _review(),
        ChatRequest(message="계약서 검토 결과를 요약해줘."),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )
    prompt = str(model.prompts[1][0].content)
    assert response.outcome == "ANSWERED"
    assert "조항 검토:" in prompt
    assert "표준조항 누락 후보:" in prompt
    assert "표준조항 누락 가능성" in prompt


@pytest.mark.asyncio
async def test_clause_category_route_uses_mcp_category_label() -> None:
    runtime = _runtime()
    model = Model(
        QuestionCategory.CLAUSE_CATEGORY, "제1조는 과업범위 및 담당업무 카테고리입니다."
    )
    response = await answer_review_question(
        _review(),
        ChatRequest(
            message="제1조의 조항 카테고리는 무엇인가요?", focus_clause_id="uc_scope"
        ),
        runtime=runtime,
        router_model=model,
        model=model,
        settings=_settings(),
    )
    assert response.outcome == "ANSWERED"
    assert "과업범위 / 담당업무" in str(model.prompts[1][0].content)
    assert runtime.tools[0].calls == [{}]
    assert not runtime.tools[2].calls


@pytest.mark.asyncio
async def test_out_of_scope_stops_before_context_and_answer() -> None:
    runtime = _runtime()
    model = Model(QuestionCategory.OUT_OF_SCOPE)
    response = await answer_review_question(
        _review(),
        ChatRequest(message="오늘 날씨는 어때?"),
        runtime=runtime,
        router_model=model,
        model=model,
        settings=_settings(),
    )
    assert response.outcome == "REFUSED"
    assert response.answer == "제공된 문서에서 관련 정보를 찾을 수 없습니다."
    assert len(model.prompts) == 1
    assert not any(tool.calls for tool in runtime.tools)


@pytest.mark.asyncio
async def test_legal_route_without_grounding_does_not_call_answer_model() -> None:
    runtime = _runtime()
    runtime.tools[2].payload = {
        "status": "NO_RESULT",
        "category": {"label": "과업범위 / 담당업무"},
        "grounding": [],
    }
    router = Model(QuestionCategory.LEGAL_GROUNDING)
    answer = Model("근거 없는 답변")
    response = await answer_review_question(
        _review(),
        ChatRequest(
            message="제1조의 법령 근거는 무엇인가요?", focus_clause_id="uc_scope"
        ),
        runtime=runtime,
        router_model=router,
        model=answer,
        settings=_settings(),
    )
    assert response.outcome == "REFUSED"
    assert response.answer == "제공된 문서에서 관련 정보를 찾을 수 없습니다."
    assert not answer.prompts


@pytest.mark.asyncio
async def test_invalid_output_timeout_review_and_focus_errors() -> None:
    blank = await answer_review_question(
        _review(),
        ChatRequest(message="요약해줘"),
        runtime=_runtime(),
        router_model=Model(QuestionCategory.REVIEW_RESULT),
        model=Model(" "),
        settings=_settings(),
    )
    assert blank.outcome == "LLM_OUTPUT_INVALID"
    with pytest.raises(ExternalServiceTimeoutError):
        await answer_review_question(
            _review(),
            ChatRequest(message="요약해줘"),
            runtime=_runtime(),
            router_model=SlowModel(),
            model=Model("답변"),
            settings=_settings(),
            llm_policy=LLMPolicy(timeout_seconds=0.01),
        )
    reviewing = _review()
    reviewing._state = ReviewState.REVIEWING
    with pytest.raises(ConflictError):
        await answer_review_question(
            reviewing,
            ChatRequest(message="설명해줘"),
            runtime=_runtime(),
            router_model=Model(QuestionCategory.CLAUSE),
            model=Model("답변"),
            settings=_settings(),
        )
    with pytest.raises(AppValidationError):
        await answer_review_question(
            _review(),
            ChatRequest(message="설명해줘", focus_clause_id="unknown"),
            runtime=_runtime(),
            router_model=Model(QuestionCategory.CLAUSE),
            model=Model("답변"),
            settings=_settings(),
        )


def test_service_is_small_graph_without_regex() -> None:
    source = Path("app/domains/chat/service.py").read_text(encoding="utf-8")
    assert "import re" not in source
    assert "StateGraph" in source and "add_conditional_edges" in source
