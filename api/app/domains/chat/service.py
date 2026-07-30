"""질문을 분류해 필요한 MCP 문맥만 답변 모델에 전달한다."""

import asyncio
from enum import StrEnum
from typing import Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from app.config import Settings
from app.core.common.errors import (
    AppValidationError,
    ConflictError,
    ExternalServiceError,
    ExternalServiceTimeoutError,
)
from app.core.llm.mcp.types import WorkShieldMCPRuntime
from app.core.llm.policy import DEFAULT_LLM_POLICY, LLMPolicy
from app.domains.chat.schemas import ChatRequest, ChatResponse, ChatSource
from app.domains.grounding.schemas import GroundingStatus
from app.domains.grounding.service import get_review_grounding
from app.domains.metadata.service import RESULT_CODE_LABELS
from app.domains.review_sessions.service import _tool_payload
from app.domains.reviews.context import (
    clause_category,
    clause_display_label,
    clause_results,
    find_user_clause,
    standard_clause,
    user_clause_id,
)
from app.domains.reviews.domain import Review, ReviewState


class QuestionCategory(StrEnum):
    CLAUSE = "조항 질문"
    REVIEW_RESULT = "검토 결과 질문"
    CLASSIFICATION = "검토 분류 질문"
    CLAUSE_CATEGORY = "조항 카테고리 질문"
    LEGAL_GROUNDING = "조항 법령 근거 질문"
    OUT_OF_SCOPE = "선정 불가"


class GraphState(TypedDict, total=False):
    category: QuestionCategory | None
    context: str
    grounded: bool
    labels: dict[str, str]
    sources: list[ChatSource]
    response: ChatResponse


ROUTER_PROMPT = """계약 검토 질문 분류기입니다. 아래 라벨 하나만 출력하세요.
조항 질문: 특정 조항의 내용·표준조항 비교
검토 결과 질문: 계약서 전체 요약·검토 결과
검토 분류 질문: 상태·별도 확인·주의 신호의 뜻
조항 카테고리 질문: 과업범위 등 카테고리의 뜻
조항 법령 근거 질문: 법령명·조문·법령 원문
선정 불가: 계약 검토 자료로 답할 수 없는 질문
예시:
"이 조항은 무슨 뜻인가요?" → 조항 질문
"계약서 결과를 요약해줘" → 검토 결과 질문
"별도 확인 필요는 무슨 뜻인가요?" → 검토 분류 질문
"과업범위 카테고리를 설명해줘" → 조항 카테고리 질문
"관련 법령과 조문은?" → 조항 법령 근거 질문
"오늘 날씨는?" → 선정 불가
이전 대화: {history}
질문: {question}"""
BASE_PROMPT = """제공된 문서만 사용하는 계약 검토 답변 어시스턴트입니다.
규칙: 문서 밖의 사실을 추측하지 마세요. 답이 없으면 \"제공된 문서에서 관련 정보를 찾을 수 없습니다.\"만 출력하세요. 상태·카테고리는 라벨로 표시하세요. 위법·적법 등 법률 판단을 하지 마세요. 문서명·조문이 있으면 표시하세요. 한국어로 간결하게 답하세요.
질문 유형: {category}
유형 지침: {instruction}
<검색된 문서>:
{context}

사용자 질문:
{question}"""
CATEGORY_PROMPTS = {
    QuestionCategory.CLAUSE: "질문과 선택 조항만 설명하고 다른 조항을 임의로 고르지 마세요.",
    QuestionCategory.REVIEW_RESULT: "개별 조항 하나로 결론 내리지 말고 조항 검토와 누락 후보를 구분해 요약하세요.",
    QuestionCategory.CLASSIFICATION: "검토 상태와 주의 문구 유사 신호의 제공된 의미만 설명하세요.",
    QuestionCategory.CLAUSE_CATEGORY: "MCP가 제공한 카테고리 이름과 설명만 답하세요.",
    QuestionCategory.LEGAL_GROUNDING: "MCP 조회가 완료된 법령명·조문·원문만 참고자료로 답하세요.",
}
EMPTY = "제공된 문서에서 관련 정보를 찾을 수 없습니다."
DISCLAIMER = (
    "표준계약서 대비 검토 후보와 법령 참고자료에 한정하며 법률 자문이 아닙니다."
)
MAX_CONTEXT_CHARS = 512


def _reply(
    outcome: str, answer: str | None, refused: bool = False, **kwargs: object
) -> ChatResponse:
    return ChatResponse(
        outcome=outcome,
        answer=answer,
        refused=refused,
        tool_status="NOT_REQUESTED",
        disclaimer=DISCLAIMER,
        **kwargs,
    )


async def _invoke(model: BaseChatModel, prompt: str, timeout: float) -> str:
    try:
        result = await asyncio.wait_for(
            model.ainvoke([HumanMessage(content=prompt)]), timeout=timeout
        )
    except (TimeoutError, asyncio.TimeoutError) as error:
        raise ExternalServiceTimeoutError(
            code="LLM_TIMEOUT",
            message="답변 생성 시간이 초과되었습니다.",
            retryable=True,
            next_action="RETRY",
        ) from error
    except ConnectionError as error:
        raise ExternalServiceError(
            code="LLM_CONNECTION_FAILED",
            message="답변 생성 서비스에 연결하지 못했습니다.",
            retryable=True,
            next_action="RETRY",
        ) from error
    except Exception as error:
        raise ExternalServiceError(
            code="LLM_OUTPUT_INVALID",
            message="답변을 생성하지 못했습니다.",
            retryable=False,
        ) from error
    return str(getattr(result, "content", "")).strip()


async def _tool(runtime: WorkShieldMCPRuntime, name: str) -> dict[str, Any]:
    tool = next((item for item in runtime.tools if item.name == name), None)
    if tool is None:
        raise ExternalServiceError(
            code="MCP_TOOL_UNAVAILABLE",
            message="검토 참고자료 조회 기능을 사용할 수 없습니다.",
            retryable=True,
        )
    try:
        return _tool_payload(await tool.ainvoke({}))
    except Exception as error:
        raise ExternalServiceError(
            code="MCP_CONNECTION_FAILED",
            message="검토 참고자료를 조회하지 못했습니다.",
            retryable=True,
        ) from error


def _labels(data: dict[str, Any], key: str, code: str, label: str) -> dict[str, str]:
    return {
        item[code]: item[label]
        for item in data.get(key, [])
        if isinstance(item, dict)
        and isinstance(item.get(code), str)
        and isinstance(item.get(label), str)
    }


def _fact(item: dict[str, Any], labels: dict[str, str], include_text: bool) -> str:
    user = item.get("user_clause")
    standard = standard_clause(item) or {}
    signals = item.get("toxic_patterns")
    values = [
        clause_display_label(user, standard.get("title")),
        RESULT_CODE_LABELS.get(str(item.get("deviation")), "검토 상태 확인 필요"),
    ]
    if category := clause_category(item):
        values.append(labels.get(category))
    if isinstance(signals, list):
        values.extend(
            labels.get(value, "주의 문구 유사 신호")
            for value in signals
            if isinstance(value, str)
        )
    if include_text:
        values.extend(
            (
                str(user)[:90] if user else None,
                str(standard.get("text"))[:90] if standard.get("text") else None,
            )
        )
    return " / ".join(value for value in values if value)


async def _context(
    category: QuestionCategory,
    review: Review,
    payload: ChatRequest,
    focused: dict[str, Any] | None,
    runtime: WorkShieldMCPRuntime,
    settings: Settings,
) -> tuple[str, bool, dict[str, str], list[ChatSource]]:
    users = [focused] if focused else clause_results(review.result)[:3]
    missing = [
        item
        for item in review.result.get("missing_standard_clauses", [])
        if isinstance(item, dict)
    ][:2]
    labels: dict[str, str] = {}
    if category is QuestionCategory.CLAUSE_CATEGORY:
        labels.update(
            _labels(
                await _tool(runtime, "list_categories"),
                "categories",
                "value",
                "description",
            )
        )
    if category in {QuestionCategory.CLASSIFICATION, QuestionCategory.REVIEW_RESULT}:
        labels.update(
            _labels(
                await _tool(runtime, "list_toxic_pattern_details"),
                "patterns",
                "pattern",
                "title",
            )
        )
    history = " / ".join(
        f"{item.get('role', '')}: {' '.join(item.get('content', '').split())[:40]}"
        for item in payload.history
    )
    sections = [f"대화 기록: {history}"] if history else []
    sections.append(
        "조항 검토: "
        + "; ".join(
            _fact(item, labels, category is QuestionCategory.CLAUSE) for item in users
        )
    )
    if category is QuestionCategory.REVIEW_RESULT and missing:
        sections.append(
            "표준조항 누락 후보: "
            + "; ".join(_fact(item, labels, False) for item in missing)
        )
    sources = (
        [
            ChatSource(
                type="USER_CLAUSE",
                id=user_clause_id(focused),
                display_label=clause_display_label(focused.get("user_clause")),
            )
        ]
        if focused
        else []
    )
    if category is QuestionCategory.LEGAL_GROUNDING:
        categories = list(
            dict.fromkeys(filter(None, (clause_category(item) for item in users)))
        )
        grounds = await asyncio.gather(
            *(
                get_review_grounding(review, value, runtime, settings)
                for value in categories
            )
        )
        laws = [
            item
            for ground in grounds
            if ground.grounding_status is GroundingStatus.OK
            for item in ground.items[:1]
        ]
        sections.append(
            "MCP 법령 참고자료: "
            + "; ".join(
                f"{item.law_name or ''} {item.article or ''} {item.text[:90]}"
                for item in laws
            )
        )
        sources.extend(
            ChatSource(
                type="LAW",
                id=item.source_id,
                display_label=" ".join(filter(None, (item.law_name, item.article))),
                law_name=item.law_name,
                article=item.article,
                source_url=item.source_url,
            )
            for item in laws
        )
    grounded = bool(users or missing)
    if category is QuestionCategory.CLAUSE_CATEGORY:
        grounded = any(clause_category(item) in labels for item in users)
    if category is QuestionCategory.LEGAL_GROUNDING:
        grounded = bool(laws)
    return "\n".join(sections)[:MAX_CONTEXT_CHARS], grounded, labels, sources


def _category(value: str) -> QuestionCategory | None:
    return next(
        (category for category in QuestionCategory if value == category.value), None
    )


async def answer_review_question(
    review: Review,
    payload: ChatRequest,
    *,
    runtime: WorkShieldMCPRuntime,
    router_model: BaseChatModel,
    model: BaseChatModel,
    settings: Settings,
    llm_policy: LLMPolicy = DEFAULT_LLM_POLICY,
) -> ChatResponse:
    """분류 모델과 답변 모델을 LangGraph 노드로 분리한다."""
    if review.state is not ReviewState.COMPLETED or not review.result:
        raise ConflictError(
            code="REVIEW_NOT_COMPLETED", message="완료된 검토에서만 질문할 수 있습니다."
        )
    if llm_policy.temperature != 0:
        raise ValueError("Chat temperature는 0이어야 합니다.")
    focused = (
        find_user_clause(review.result, payload.focus_clause_id)
        if payload.focus_clause_id
        else None
    )
    if payload.focus_clause_id and focused is None:
        raise AppValidationError(
            code="FOCUS_CLAUSE_NOT_FOUND",
            message="현재 검토 결과에 없는 조항입니다.",
            field="focus_clause_id",
        )

    async def classify(_state: GraphState) -> GraphState:
        history = " / ".join(
            str(item.get("content", ""))[:40] for item in payload.history
        )
        value = await _invoke(
            router_model,
            ROUTER_PROMPT.format(history=history, question=payload.message[:80]),
            min(20, llm_policy.timeout_seconds),
        )
        return {"category": _category(value)}

    async def prepare(state: GraphState) -> GraphState:
        category = state["category"]
        assert category is not None
        context, grounded, labels, sources = await _context(
            category, review, payload, focused, runtime, settings
        )
        return {
            "context": context,
            "grounded": grounded,
            "labels": labels,
            "sources": sources,
        }

    async def answer(state: GraphState) -> GraphState:
        category = state["category"]
        assert category is not None
        prompt = BASE_PROMPT.format(
            category=category,
            instruction=CATEGORY_PROMPTS[category],
            context=state["context"],
            question=payload.message[:80],
        )
        text = (await _invoke(model, prompt, llm_policy.timeout_seconds))[:400]
        for code, label in {**RESULT_CODE_LABELS, **state["labels"]}.items():
            text = text.replace(code, label)
        response = (
            _reply(
                "LLM_OUTPUT_INVALID",
                None,
                True,
                limitations=["답변을 생성하지 못했습니다."],
            )
            if not text
            else _reply(
                "REFUSED" if text == EMPTY else "ANSWERED",
                text,
                text == EMPTY,
                sources=state["sources"],
            )
        )
        return {"response": response}

    async def reject(state: GraphState) -> GraphState:
        response = (
            _reply(
                "LLM_OUTPUT_INVALID",
                None,
                True,
                limitations=["질문 유형을 분류하지 못했습니다."],
            )
            if state["category"] is None
            else _reply("REFUSED", EMPTY, True)
        )
        return {"response": response}

    graph = StateGraph(GraphState)
    graph.add_node("classify", classify)
    graph.add_node("prepare", prepare)
    graph.add_node("answer", answer)
    graph.add_node("reject", reject)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        lambda state: (
            "prepare"
            if state["category"] not in {None, QuestionCategory.OUT_OF_SCOPE}
            else "reject"
        ),
    )
    graph.add_conditional_edges(
        "prepare", lambda state: "answer" if state["grounded"] else "reject"
    )
    graph.add_edge("answer", END)
    graph.add_edge("reject", END)
    result = await graph.compile().ainvoke({})
    return result["response"]
