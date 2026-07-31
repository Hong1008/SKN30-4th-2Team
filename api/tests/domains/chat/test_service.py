"""LangGraph 질문 분류와 근거 제한을 검증한다."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from app.config import Settings
from app.core.common.errors import (
    AppValidationError,
    ConflictError,
    ExternalServiceConfigurationError,
    ExternalServiceTimeoutError,
)
from app.core.llm.policy import LLMPolicy
from app.domains.chat.schemas import ChatRefusalReason, ChatRequest
from app.domains.chat.service import (
    AnswerPlanItem,
    QuestionCategory,
    _normalize_answer,
    _token_aware_segments,
    answer_review_question,
    stream_review_answer,
)
from app.domains.chat.context_service import ChatContextState, ChatContextTargetKind
from app.domains.reviews.domain import MCPReviewStatus, Review, ReviewState


class Tool:
    def __init__(self, name: str, payload: dict[str, object]) -> None:
        self.name, self.payload, self.calls = name, payload, []

    async def ainvoke(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(payload)
        return self.payload


class Model:
    def __init__(self, *answers: object) -> None:
        self.answers, self.prompts = list(answers), []
        self.structured_schema: type[BaseModel] | None = None

    def with_structured_output(
        self,
        schema: type[BaseModel],
        *,
        method: str,
        include_raw: bool,
    ) -> "Model":
        assert method == "json_schema"
        assert include_raw is True
        self.structured_schema = schema
        return self

    async def ainvoke(self, prompt: list[object]) -> AIMessage | dict[str, object]:
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if self.structured_schema is not None:
            schema, self.structured_schema = self.structured_schema, None
            try:
                parsed = schema(category=answer)
                parsing_error = None
            except Exception as error:
                parsed = None
                parsing_error = error
            return {
                "raw": AIMessage(content=str(answer)),
                "parsed": parsed,
                "parsing_error": parsing_error,
            }
        return AIMessage(content=answer)


class SlowModel:
    def with_structured_output(
        self,
        _schema: type[BaseModel],
        *,
        method: str,
        include_raw: bool,
    ) -> "SlowModel":
        assert method == "json_schema"
        assert include_raw is True
        return self

    async def ainvoke(self, _prompt: list[object]) -> AIMessage:
        await asyncio.sleep(0.1)
        return AIMessage(content="늦은 답변")


class ProviderError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FailingRouterModel:
    def with_structured_output(
        self,
        _schema: type[BaseModel],
        *,
        method: str,
        include_raw: bool,
    ) -> "FailingRouterModel":
        assert method == "json_schema"
        assert include_raw is True
        return self

    async def ainvoke(self, _prompt: list[object]) -> dict[str, object]:
        raise ProviderError(401)


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
async def test_service_policy_uses_existing_pydantic_description_without_model() -> None:
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
    assert response.outcome == "ANSWERED"
    assert response.question_category == "SERVICE_POLICY"
    assert response.answer is not None and "탐지된 독소/주의 패턴 코드 목록" in response.answer
    assert not model.prompts
    assert not runtime.tools[2].calls


@pytest.mark.asyncio
async def test_clause_signal_question_uses_only_saved_labels_for_that_clause() -> None:
    review = _review()
    review.result["clause_results"][0]["toxic_patterns"] = [
        "UNPAID_ADDITIONAL_WORK",
        "UNILATERAL_INTERPRETATION",
    ]
    review.result["toxic_pattern_labels"] = {
        "UNPAID_ADDITIONAL_WORK": "무상 추가 업무 요구",
        "UNILATERAL_INTERPRETATION": "일방적 해석 권한",
    }
    model = Model()

    response = await answer_review_question(
        review,
        ChatRequest(message="왜 제1조는 주의 신호가 있는건가요"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    assert response.question_category == "CONTRACT_CONTENT"
    assert response.answer is not None
    assert "무상 추가 업무 요구" in response.answer
    assert "일방적 해석 권한" in response.answer
    assert "UNPAID_ADDITIONAL_WORK" not in response.answer
    assert "UNILATERAL_INTERPRETATION" not in response.answer
    assert "제2조" not in response.answer
    assert not model.prompts


@pytest.mark.asyncio
async def test_signal_identification_does_not_fetch_grounding() -> None:
    runtime = _runtime()
    review = _review()
    review.result["toxic_pattern_labels"] = {
        "UNILATERAL_CHANGE": "일방적인 과업 범위 변경 권한"
    }

    response = await answer_review_question(
        review,
        ChatRequest(message="제2조의 주의 신호는 어떤 건가요?"),
        runtime=runtime,
        router_model=Model(),
        model=Model(),
        settings=_settings(),
    )

    assert response.question_category == "CONTRACT_CONTENT"
    assert not runtime.tools[2].calls


@pytest.mark.asyncio
async def test_signal_impact_question_attaches_category_grounding() -> None:
    review = _review()
    review.result["clause_results"][0]["toxic_patterns"] = ["IP_FREE_ASSIGNMENT"]
    review.result["toxic_pattern_labels"] = {
        "IP_FREE_ASSIGNMENT": "저작권·지식재산권 전부 무상 귀속"
    }
    runtime = _runtime()
    router = Model(QuestionCategory.CONTRACT_CONTENT)
    answer = Model("제1조의 조항 내용을 설명합니다.\n\n## 법령 참고자료\n\n민법 제390조 원문입니다.")

    response = await answer_review_question(
        review,
        ChatRequest(message="저작권을 무상으로 귀속하면 어떤 문제가 있나요?"),
        runtime=runtime,
        router_model=router,
        model=answer,
        settings=_settings(),
        conversation_context=ChatContextState(
            category="CONTRACT_CONTENT",
            target_kind=ChatContextTargetKind.SINGLE_CLAUSE,
            selected_clause_ids=["uc_scope"],
        ),
    )

    assert response.outcome == "ANSWERED"
    prompt = str(answer.prompts[0][0].content)
    assert "제1조 업무 범위는 API 개발로 한다." in prompt
    assert "업무 범위는 별지에서 구체적으로 정한다." in prompt
    assert "법령 참고자료: 민법 제390조" in prompt
    assert "원문: 손해배상 참고 원문" in prompt
    assert [(source.type, source.id) for source in response.sources] == [
        ("USER_CLAUSE", "uc_scope"),
        ("LAW", "law_1"),
    ]
    assert runtime.tools[2].calls == [
        {"contract_type": "SW_FREELANCE", "category": "SCOPE_SOW"}
    ]


@pytest.mark.asyncio
async def test_signal_impact_without_grounding_keeps_clause_explanation() -> None:
    review = _review()
    review.result["clause_results"][0]["toxic_patterns"] = ["IP_FREE_ASSIGNMENT"]
    runtime = _runtime()
    runtime.tools[2].payload = {
        "status": "NO_RESULT",
        "category": {"label": "과업범위 / 담당업무"},
        "grounding": [],
    }
    router = Model(QuestionCategory.CONTRACT_CONTENT)
    answer = Model("제1조의 사용자 조항과 표준조항 후보를 설명합니다.")

    response = await answer_review_question(
        review,
        ChatRequest(message="제1조에서 저작권을 무상으로 귀속하면 어떤 문제가 있나요?"),
        runtime=runtime,
        router_model=router,
        model=answer,
        settings=_settings(),
    )

    assert response.outcome == "ANSWERED"
    assert response.answer is not None
    assert "제1조의 사용자 조항" in response.answer
    assert "연결된 법령 참고자료는 현재 검토 결과에 없습니다." in response.answer


@pytest.mark.asyncio
async def test_clause_signal_question_hides_unknown_code_with_field_description() -> None:
    review = _review()
    review.result["clause_results"][0]["toxic_patterns"] = ["UNKNOWN_SIGNAL"]
    model = Model()

    response = await answer_review_question(
        review,
        ChatRequest(message="제1조 주의 신호 이유가 뭐야"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    assert response.answer is not None
    assert "탐지된 독소/주의 패턴 코드 목록" in response.answer
    assert "UNKNOWN_SIGNAL" not in response.answer


@pytest.mark.asyncio
async def test_review_wide_signal_question_lists_only_clauses_with_saved_labels() -> None:
    review = _review()
    review.result["toxic_pattern_labels"] = {
        "UNILATERAL_CHANGE": "일방적인 과업 범위 변경 권한"
    }
    model = Model()

    response = await answer_review_question(
        review,
        ChatRequest(message="제 계약서의 주의 신호"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    assert response.question_category == "REVIEW_ANALYSIS"
    assert response.answer is not None
    assert "제2조" in response.answer
    assert "일방적인 과업 범위 변경 권한" in response.answer
    assert "제1조" not in response.answer
    assert not model.prompts


@pytest.mark.asyncio
async def test_clause_wording_normalizes_article_number_for_signal_question() -> None:
    model = Model()

    response = await answer_review_question(
        _review(),
        ChatRequest(message="조항 1의 주의 신호"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    assert response.question_category == "CONTRACT_CONTENT"
    assert response.answer is not None
    assert "제1조" in response.answer
    assert "포함되어 있지 않습니다" in response.answer
    assert "SERVICE_POLICY" not in response.answer
    assert not model.prompts


@pytest.mark.asyncio
async def test_review_wide_signal_question_says_when_no_signal_is_recorded() -> None:
    review = _review()
    review.result["clause_results"][1]["toxic_patterns"] = []

    response = await answer_review_question(
        review,
        ChatRequest(message="계약서 전체의 주의 신호가 무엇인가요?"),
        runtime=_runtime(),
        router_model=Model(),
        model=Model(),
        settings=_settings(),
    )

    assert response.question_category == "REVIEW_ANALYSIS"
    assert response.answer is not None and "기록된" in response.answer


@pytest.mark.asyncio
async def test_answer_prompt_uses_saved_signal_label_not_internal_code() -> None:
    review = _review()
    review.result["toxic_pattern_labels"] = {
        "UNILATERAL_CHANGE": "일방적인 과업 범위 변경 권한"
    }
    model = Model(QuestionCategory.CONTRACT_CONTENT, "제2조 설명입니다.")

    await answer_review_question(
        review,
        ChatRequest(message="제2조를 설명해줘"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    prompt = str(model.prompts[1][0].content)
    assert "일방적인 과업 범위 변경 권한" in prompt
    assert "UNILATERAL_CHANGE" not in prompt


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
    prompt = str(model.prompts[1][0].content)
    assert "제1조 업무 범위는 API 개발로 한다." in prompt
    assert "업무 범위는 별지에서 구체적으로 정한다." in prompt
    assert "법령 참고자료: 민법 제390조" in prompt
    assert "원문: 손해배상 참고 원문" in prompt
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
async def test_article_number_in_question_selects_matching_clause() -> None:
    review = _review()
    review.result["clause_results"].append(
        {
            "user_clause_id": "uc_copyright",
            "user_clause": "제11조 산출물의 저작권은 협의한다.",
            "deviation": "EXTRA",
            "toxic_patterns": [],
            "match": {
                "status": "CANDIDATE_SELECTED",
                "standard": {
                    "clause_id": "std_copyright",
                    "category": "IP_OWNERSHIP",
                    "title": "제11조 저작권",
                    "text": "산출물 저작권 귀속 기준을 정한다.",
                },
            },
        }
    )
    model = Model(QuestionCategory.CLAUSE, "제11조의 비교 근거입니다.")

    response = await answer_review_question(
        review,
        ChatRequest(message="제11조는 신경 안 써도 됨?"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    prompt = str(model.prompts[1][0].content)
    assert "제11조 산출물의 저작권은 협의한다." in prompt
    assert "산출물 저작권 귀속 기준을 정한다." in prompt
    assert "제1조 업무 범위는 API 개발로 한다." not in prompt
    assert [(source.type, source.id) for source in response.sources] == [
        ("USER_CLAUSE", "uc_copyright")
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
    assert "사용자 조항 원문: 제1조 업무 범위는 API 개발로 한다." in prompt
    assert "검토 상태: 별도 확인 필요" in prompt
    assert "표준조항 누락 가능성" in prompt


@pytest.mark.asyncio
async def test_review_result_summarizes_all_flagged_clauses_for_comparison() -> None:
    review = _review()
    for number in range(3, 12):
        review.result["clause_results"].append(
            {
                "user_clause_id": f"uc_{number}",
                "user_clause": f"제{number}조 추가 확인 조항입니다.",
                "deviation": "EXTRA",
                "toxic_patterns": [],
                "match": {"status": "NO_CANDIDATE"},
            }
        )
    model = Model(
        QuestionCategory.REVIEW_RESULT,
        "첫 번째 묶음",
        "두 번째 묶음",
        "세 번째 묶음",
        "네 번째 묶음",
    )

    await answer_review_question(
        review,
        ChatRequest(message="별도 확인이 필요한 조항을 표준조항과 비교해 줘"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    prompts = [str(prompt[0].content) for prompt in model.prompts]
    assert len(prompts) == 4
    assert "제2조 갑은 업무 내용을 필요에 따라 변경할 수 있다." in prompts[0]
    assert "제11조 추가 확인 조항입니다." in prompts[-1]


@pytest.mark.asyncio
async def test_router_uses_recent_history_for_follow_up_question() -> None:
    model = Model(QuestionCategory.REVIEW_RESULT, "전체 결과를 확인했습니다.")

    await answer_review_question(
        _review(),
        ChatRequest(
            message="11개 아니야?",
            history=[{"role": "user", "content": "별도 확인 필요한 조항 수 알려 줘"}],
        ),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    assert "별도 확인 필요한 조항 수 알려 줘" not in str(model.prompts[0][0].content)
    answer_prompt = str(model.prompts[1][0].content)
    assert "<이전 대화: 맥락 전용>" in answer_prompt
    assert "반드시 현재 사용자 질문에만 답하세요." in answer_prompt
    assert "11개 아니야?" in answer_prompt


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
    assert "업무 범위는 별지에서 구체적으로 정한다." in str(model.prompts[1][0].content)
    assert "SCOPE_SOW" not in str(model.prompts[1][0].content)
    assert not runtime.tools[0].calls
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
    assert response.answer is None
    assert response.refusal_reason is ChatRefusalReason.OUT_OF_SCOPE
    assert response.limitations == [
        "현재 질문은 계약 검토 결과·표준조항·법령 참고자료 범위를 벗어나므로 답변할 수 없습니다."
    ]
    assert len(model.prompts) == 1
    assert not any(tool.calls for tool in runtime.tools)


@pytest.mark.asyncio
async def test_invalid_structured_router_output_fails_closed() -> None:
    model = Model("알 수 없는 라벨")

    response = await answer_review_question(
        _review(),
        ChatRequest(message="무엇인가요?"),
        runtime=_runtime(),
        router_model=model,
        model=Model("호출되면 안 됩니다."),
        settings=_settings(),
    )

    assert response.outcome == "LLM_OUTPUT_INVALID"
    assert response.answer is None
    assert response.refused is True


@pytest.mark.asyncio
async def test_legal_route_without_grounding_keeps_clause_and_standard_context() -> None:
    review = _review()
    review.result["clause_results"].append(
        {
            "user_clause_id": "uc_confidentiality",
            "user_clause": "제13조 비밀유지 의무를 정한다.",
            "deviation": "EXTRA",
            "toxic_patterns": [],
            "match": {
                "status": "CANDIDATE_SELECTED",
                "standard": {
                    "clause_id": "std_confidentiality",
                    "category": "CONFIDENTIALITY",
                    "title": "비밀유지",
                    "text": "업무 중 알게 된 비밀정보를 보호한다.",
                },
            },
        }
    )
    runtime = _runtime()
    runtime.tools[2].payload = {
        "status": "NO_RESULT",
        "category": {"label": "과업범위 / 담당업무"},
        "grounding": [],
    }
    router = Model(QuestionCategory.LEGAL_GROUNDING)
    answer = Model("제13조의 사용자 조항과 표준조항 후보를 설명합니다.")
    response = await answer_review_question(
        review,
        ChatRequest(message="13조에 대한 구체적인 법률 설명을 해줄 수 있어?"),
        runtime=runtime,
        router_model=router,
        model=answer,
        settings=_settings(),
    )
    assert response.outcome == "ANSWERED"
    assert response.answer is not None
    assert "제13조의 사용자 조항" in response.answer
    assert "연결된 법령 참고자료는 현재 검토 결과에 없습니다." in response.answer
    prompt = str(answer.prompts[0][0].content)
    assert "제13조 비밀유지 의무를 정한다." in prompt
    assert "업무 중 알게 된 비밀정보를 보호한다." in prompt


@pytest.mark.asyncio
async def test_legal_reference_notice_is_sent_in_stream_and_final_response() -> None:
    runtime = _runtime()
    runtime.tools[2].payload = {
        "status": "NO_RESULT",
        "category": {"label": "과업범위 / 담당업무"},
        "grounding": [],
    }
    events = [
        event
        async for event in stream_review_answer(
            _review(),
            ChatRequest(message="제1조에 대한 구체적인 법률 설명을 해줘"),
            runtime=runtime,
            router_model=Model(QuestionCategory.LEGAL_GROUNDING),
            model=Model("제1조의 사용자 조항을 설명합니다."),
            settings=_settings(),
        )
    ]

    deltas = [data["text"] for name, data in events if name == "delta"]
    completed = next(data for name, data in events if name == "completed")
    assert any("연결된 법령 참고자료는 현재 검토 결과에 없습니다." in text for text in deltas)
    assert completed.answer is not None
    assert "제1조의 사용자 조항" in completed.answer
    assert "연결된 법령 참고자료는 현재 검토 결과에 없습니다." in completed.answer


@pytest.mark.asyncio
async def test_explicit_law_original_request_stays_limited_without_grounding() -> None:
    runtime = _runtime()
    runtime.tools[2].payload = {
        "status": "NO_RESULT",
        "category": {"label": "과업범위 / 담당업무"},
        "grounding": [],
    }
    router = Model(QuestionCategory.LEGAL_GROUNDING)
    answer = Model("호출되면 안 됩니다.")

    response = await answer_review_question(
        _review(),
        ChatRequest(message="민법 제390조 원문을 보여줘", focus_clause_id="uc_scope"),
        runtime=runtime,
        router_model=router,
        model=answer,
        settings=_settings(),
    )

    assert response.outcome == "REFUSED"
    assert response.refusal_reason is ChatRefusalReason.INSUFFICIENT_GROUNDING
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
    with pytest.raises(ExternalServiceConfigurationError) as exc_info:
        await answer_review_question(
            _review(),
            ChatRequest(message="요약해줘"),
            runtime=_runtime(),
            router_model=FailingRouterModel(),
            model=Model("답변"),
            settings=_settings(),
        )
    assert exc_info.value.code == "LLM_AUTH_FAILED"
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


def test_normalize_answer_removes_legacy_headers_and_only_exact_empty_preamble() -> None:
    assert _normalize_answer(
        "[상태: 검토 결과 질문] [카테고리: 계약 검토]\n\n"
        "제공된 문서에서 관련 정보를 찾을 수 없습니다.\n\n"
        "## 별도 확인 필요\n\n제5조부터 제20조까지 11개입니다."
    ) == "## 별도 확인 필요\n\n제5조부터 제20조까지 11개입니다."
    assert _normalize_answer("제공된 문서에서 관련 정보를 찾을 수 없습니다.") == (
        "제공된 문서에서 관련 정보를 찾을 수 없습니다."
    )
    assert _normalize_answer("[상태: MISSING] [카테고리: LIABILITY] [답변:]\n내용") == "내용"


@pytest.mark.asyncio
async def test_stream_answers_all_extra_items_in_three_item_segments() -> None:
    review = _review()
    for number in range(3, 12):
        review.result["clause_results"].append(
            {
                "user_clause_id": f"uc_{number}",
                "user_clause": f"제{number}조 추가 확인 조항입니다.",
                "deviation": "EXTRA",
                "toxic_patterns": [],
                "match": {"status": "NO_CANDIDATE"},
            }
        )
    model = Model(
        QuestionCategory.REVIEW_ANALYSIS,
        "## 제2조\n\n첫 묶음",
        "## 제5조\n\n둘째 묶음",
        "## 제8조\n\n셋째 묶음",
        "## 제11조\n\n넷째 묶음",
    )

    events = [
        event
        async for event in stream_review_answer(
            review,
            ChatRequest(message="별도 확인이 필요한 조항을 모두 설명해줘"),
            runtime=_runtime(),
            router_model=model,
            model=model,
            settings=_settings(),
        )
    ]

    completed = [data for name, data in events if name == "completed"][-1]
    segments = [data for name, data in events if name == "segment_complete"]
    assert len(segments) == 4
    assert [data["segment"] for data in segments] == [
        {"index": 1, "total": 4},
        {"index": 2, "total": 4},
        {"index": 3, "total": 4},
        {"index": 4, "total": 4},
    ]
    assert completed.answer is not None and "넷째 묶음" in completed.answer
    assert len(completed.sources) == 10


@pytest.mark.asyncio
async def test_missing_follow_up_uses_last_missing_group_as_standard_clause_context() -> None:
    model = Model(QuestionCategory.CONTRACT_CONTENT, "## 대금 지급\n\n표준조항 내용입니다.")
    response = await answer_review_question(
        _review(),
        ChatRequest(message="각 조항의 내용을 설명해줘"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
        conversation_context=ChatContextState(
            category="REVIEW_ANALYSIS",
            target_kind=ChatContextTargetKind.MISSING_STANDARD_CLAUSES,
        ),
    )

    assert response.outcome == "ANSWERED"
    assert "대금 지급 기준을 정한다." in str(model.prompts[1][0].content)
    assert response.sources[0].type == "STANDARD_CLAUSE"


@pytest.mark.asyncio
async def test_large_item_is_split_without_dropping_its_context() -> None:
    item = AnswerPlanItem(
        "USER_CLAUSE",
        "large",
        "조항 요약\n\n" + ("가" * 8_000),
        (),
    )
    segments = await _token_aware_segments(
        QuestionCategory.CONTRACT_CONTENT,
        ChatRequest(message="이 조항을 설명해줘"),
        (item,),
        0,
        _settings(),
    )

    flattened = "".join(part.context for segment in segments for part in segment)
    assert len(segments) >= 2
    assert all(len(segment) <= 3 for segment in segments)
    assert flattened.count("가") == 8_000


@pytest.mark.asyncio
async def test_stream_failure_preserves_completed_segments_and_continuation() -> None:
    review = _review()
    for number in range(3, 6):
        review.result["clause_results"].append(
            {
                "user_clause_id": f"uc_{number}",
                "user_clause": f"제{number}조 추가 확인 조항입니다.",
                "deviation": "EXTRA",
                "toxic_patterns": [],
                "match": {"status": "NO_CANDIDATE"},
            }
        )
    model = Model(
        QuestionCategory.REVIEW_ANALYSIS,
        "첫 묶음 답변",
        ProviderError(503),
    )

    events = [
        event
        async for event in stream_review_answer(
            review,
            ChatRequest(message="별도 확인이 필요한 조항을 설명해줘"),
            runtime=_runtime(),
            router_model=model,
            model=model,
            settings=_settings(),
        )
    ]

    assert [name for name, _ in events].count("segment_complete") == 1
    failed = next(data for name, data in events if name == "failed")
    assert failed["partial_answer_available"] is True
    assert failed["continuation"] == {
        "next_segment_offset": 3,
        "remaining_segments": 1,
    }
    assert failed["question_category"] == "REVIEW_ANALYSIS"


@pytest.mark.asyncio
async def test_continuation_reuses_saved_category_without_rerouting() -> None:
    review = _review()
    for number in range(3, 6):
        review.result["clause_results"].append(
            {
                "user_clause_id": f"uc_{number}",
                "user_clause": f"제{number}조 추가 확인 조항입니다.",
                "deviation": "EXTRA",
                "toxic_patterns": [],
                "match": {"status": "NO_CANDIDATE"},
            }
        )
    model = Model("남은 묶음 답변")
    events = [
        event
        async for event in stream_review_answer(
            review,
            ChatRequest(message="이어서 답변해줘"),
            runtime=_runtime(),
            router_model=model,
            model=model,
            settings=_settings(),
            conversation_context=ChatContextState(
                category="REVIEW_ANALYSIS",
                target_kind=ChatContextTargetKind.RESULT_GROUP,
                result_codes=["EXTRA"],
                next_segment_offset=3,
            ),
        )
    ]

    assert len(model.prompts) == 1
    assert "제5조 추가 확인 조항입니다." in str(model.prompts[0][0].content)
    completed = next(data for name, data in events if name == "completed")
    assert completed.question_category == "REVIEW_ANALYSIS"


@pytest.mark.asyncio
async def test_status_meaning_uses_existing_result_description_without_model() -> None:
    model = Model()
    response = await answer_review_question(
        _review(),
        ChatRequest(message="별도 확인 필요는 무슨 뜻인가요?"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    assert response.question_category == "REVIEW_STATUS_DEFINITION"
    assert response.answer is not None and "별도 확인 필요" in response.answer
    assert not model.prompts


@pytest.mark.asyncio
async def test_status_list_uses_only_matching_clause_group_without_model() -> None:
    model = Model()
    response = await answer_review_question(
        _review(),
        ChatRequest(message="별도 확인 필요한 조항 전부 알려줘"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    assert response.question_category == "REVIEW_RESULT_LIST"
    assert response.answer is not None and "제2조" in response.answer
    assert response.sources[0].id == "uc_change"
    assert not model.prompts


@pytest.mark.asyncio
async def test_no_match_list_accepts_korean_particle_variant() -> None:
    review = _review()
    review.result["clause_results"][1]["deviation"] = "NO_MATCH"
    model = Model()
    response = await answer_review_question(
        review,
        ChatRequest(message="표준조항 검색 후보가 없는 조항 전부 알려줘"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    assert response.question_category == "REVIEW_RESULT_LIST"
    assert response.answer is not None and "제2조" in response.answer
    assert not model.prompts


@pytest.mark.asyncio
async def test_comparison_uses_only_requested_status_group() -> None:
    model = Model("## 제2조\n\n표준조항 후보가 없습니다.")
    response = await answer_review_question(
        _review(),
        ChatRequest(message="별도 확인 조항을 표준과 비교해줘"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    prompt = str(model.prompts[0][0].content)
    assert response.question_category == "REVIEW_CLAUSE_COMPARISON"
    assert "제2조 갑은 업무 내용을 필요에 따라 변경할 수 있다." in prompt
    assert "제1조 업무 범위는 API 개발로 한다." not in prompt
    assert "표준조항 후보: 제공되지 않음" in prompt


@pytest.mark.asyncio
async def test_priority_request_does_not_rank_clauses() -> None:
    model = Model()
    response = await answer_review_question(
        _review(),
        ChatRequest(message="수정이 시급한 조항 알려줘"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    assert response.question_category == "REVIEW_PRIORITY"
    assert response.answer == "MCP 결과에는 수정 시급성이나 우선순위 정보가 없어 특정 조항의 우선순위를 단정할 수 없습니다."
    assert not model.prompts


@pytest.mark.asyncio
async def test_signal_search_returns_only_label_matched_user_clauses() -> None:
    review = _review()
    review.result["toxic_pattern_labels"] = {
        "UNILATERAL_CHANGE": "무상 추가 업무 요구"
    }
    model = Model()
    response = await answer_review_question(
        review,
        ChatRequest(message="어떤 조항에서 추가 업무지시를 하는 뉘앙스가 있나요"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
    )

    assert response.question_category == "SIGNAL_SEARCH"
    assert response.answer is not None and "제2조" in response.answer
    assert "무상 추가 업무 요구" in response.answer
    assert "표준조항 누락 가능성" not in response.answer
    assert not model.prompts


@pytest.mark.asyncio
async def test_ambiguous_impact_follow_up_explains_last_standard_clause_group() -> None:
    model = Model("## 대금 지급\n\n대금 지급 기준을 설명합니다.")
    response = await answer_review_question(
        _review(),
        ChatRequest(message="불이익은 무엇인가요"),
        runtime=_runtime(),
        router_model=model,
        model=model,
        settings=_settings(),
        conversation_context=ChatContextState(
            category="REVIEW_RESULT_LIST",
            target_kind=ChatContextTargetKind.MISSING_STANDARD_CLAUSES,
        ),
    )

    prompt = str(model.prompts[0][0].content)
    assert response.question_category == "CONTRACT_CONTENT"
    assert "대금 지급 기준을 정한다." in prompt
    assert "실제 영향을 판단하지 말고" in prompt
