"""질문을 분류해 필요한 MCP 문맥만 답변 모델에 전달한다."""

import asyncio
from dataclasses import dataclass
from enum import StrEnum
import re
from time import perf_counter
from collections.abc import AsyncIterator
from typing import Any

import httpx

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.core.common.errors import (
    AppValidationError,
    ConflictError,
    ExternalServiceConfigurationError,
    ExternalServiceError,
    ExternalServiceTimeoutError,
    OverCapacityError,
)
from app.core.common.logging import log_event
from app.core.llm.mcp.types import WorkShieldMCPRuntime
from app.core.llm.policy import DEFAULT_LLM_POLICY, LLMPolicy
from app.domains.chat.schemas import (
    ChatRefusalReason,
    ChatRequest,
    ChatResponse,
    ChatSource,
)
from app.domains.chat.context_service import ChatContextState, ChatContextTargetKind
from app.domains.grounding.schemas import GroundingStatus
from app.domains.grounding.service import get_review_grounding
from app.domains.metadata.service import RESULT_CODE_DESCRIPTIONS, RESULT_CODE_LABELS
from app.domains.reviews.context import (
    clause_category,
    clause_article_number,
    clause_display_label,
    clause_results,
    find_user_clause,
    referenced_article_numbers,
    standard_clause,
    user_clause_id,
)
from app.domains.reviews.domain import Review, ReviewState
from app.domains.reviews.schemas import MCPClauseReviewCandidate, MCPStandardClause


class QuestionCategory(StrEnum):
    """채팅 답변의 안정적인 공개 분류 코드."""

    CONTRACT_CONTENT = "CONTRACT_CONTENT"
    REVIEW_ANALYSIS = "REVIEW_ANALYSIS"
    REVIEW_STATUS_DEFINITION = "REVIEW_STATUS_DEFINITION"
    REVIEW_RESULT_LIST = "REVIEW_RESULT_LIST"
    REVIEW_CLAUSE_COMPARISON = "REVIEW_CLAUSE_COMPARISON"
    REVIEW_PRIORITY = "REVIEW_PRIORITY"
    SIGNAL_SEARCH = "SIGNAL_SEARCH"
    LEGAL_REFERENCE = "LEGAL_REFERENCE"
    SERVICE_POLICY = "SERVICE_POLICY"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"

    # 기존 클라이언트·테스트가 보낸 라벨은 새 네 가지 공개 코드로만 해석한다.
    CLAUSE = CONTRACT_CONTENT
    REVIEW_RESULT = REVIEW_ANALYSIS
    CLASSIFICATION = REVIEW_ANALYSIS
    CLAUSE_CATEGORY = CONTRACT_CONTENT
    LEGAL_GROUNDING = LEGAL_REFERENCE


class RouterDecision(BaseModel):
    """외부 분류기가 반환해야 하는 단일 질문 유형."""

    category: QuestionCategory


ANSWER_SEGMENT_SIZE = 3
MAX_PROMPT_TOKENS = 7_104


@dataclass(frozen=True, slots=True)
class AnswerPlanItem:
    """LLM 한 번이 설명할 하나의 검증된 검토 대상."""

    kind: str
    identifier: str
    context: str
    sources: tuple[ChatSource, ...]


@dataclass(frozen=True, slots=True)
class AnswerPlan:
    """질문에 맞춰 결정론적으로 만든 순서 보존 답변 계획."""

    target_kind: str
    result_codes: tuple[str, ...]
    items: tuple[AnswerPlanItem, ...]
    legal_reference_notice: str | None = None


ROUTER_PROMPT = """계약 검토 질문 분류기입니다. 아래 코드 하나만 출력하세요.
CONTRACT_CONTENT: 특정 조항, 표준조항, 카테고리의 내용·비교
REVIEW_ANALYSIS: 계약서 전체 결과, 상태, 별도 확인, 주의 신호, 여러 조항 목록
REVIEW_STATUS_DEFINITION: 검토 상태의 뜻 또는 해석 기준
REVIEW_RESULT_LIST: 특정 검토 상태 조항의 전체 목록·개수
REVIEW_CLAUSE_COMPARISON: 검토 대상 조항과 표준조항 후보의 항목별 비교
REVIEW_PRIORITY: 수정 시급성·긴급도·우선순위 질문
SIGNAL_SEARCH: 특정 주의 문구와 유사한 조항 찾기
LEGAL_REFERENCE: 법령명, 조문, 법령 원문 참고자료
SERVICE_POLICY: 표준조항·검토 상태·주의 신호의 서비스 운영 기준과 용어
OUT_OF_SCOPE: 계약 검토 자료로 답할 수 없는 질문
예시:
"이 조항은 무슨 뜻인가요?" → CONTRACT_CONTENT
"계약서 결과를 요약해줘" → REVIEW_ANALYSIS
"별도 확인 필요는 무슨 뜻인가요?" → REVIEW_STATUS_DEFINITION
"별도 확인 필요한 조항 전부 알려줘" → REVIEW_RESULT_LIST
"별도 확인 조항을 표준과 비교해줘" → REVIEW_CLAUSE_COMPARISON
"수정이 시급한 조항은?" → REVIEW_PRIORITY
"과업범위 카테고리를 설명해줘" → CONTRACT_CONTENT
"관련 법령과 조문은?" → LEGAL_REFERENCE
"별도 확인 필요는 어떻게 선정되나요?" → SERVICE_POLICY
"오늘 날씨는?" → OUT_OF_SCOPE
질문: {question}"""
TOXIC_PATTERNS_DESCRIPTION = (
    MCPClauseReviewCandidate.model_fields["toxic_patterns"].description
    or "탐지된 주의 문구 목록"
)
REVIEW_SIGNAL_GUIDE = f"""검토 신호의 플랫폼 기준:
- {RESULT_CODE_LABELS['NONE']}: {RESULT_CODE_DESCRIPTIONS['NONE']}
- {RESULT_CODE_LABELS['EXTRA']}: {RESULT_CODE_DESCRIPTIONS['EXTRA']}
- {RESULT_CODE_LABELS['NO_MATCH']}: {RESULT_CODE_DESCRIPTIONS['NO_MATCH']}
- {RESULT_CODE_LABELS['MISSING']}: {RESULT_CODE_DESCRIPTIONS['MISSING']}
- {TOXIC_PATTERNS_DESCRIPTION}: 표준 대비 상태와 독립적인 알려진 주의 문구 유사 신호입니다. 빈 목록은 안전성·적법성 판단이 아닙니다.
개별 조항의 이유는 제공된 검토 상태, 표준조항 후보 유무, 주의 문구 유사 신호만 사용하세요. 제공되지 않은 위험성·불공정성·분쟁 가능성·법적 결론을 추정하지 마세요."""

BASE_PROMPT = """제공된 문서만 사용하는 계약 검토 답변 어시스턴트입니다.
규칙: 문서 밖의 사실을 추측하지 마세요. 답이 없으면 \"제공된 문서에서 관련 정보를 찾을 수 없습니다.\"만 출력하세요. 위법·적법 등 법률 판단을 하지 마세요. MCP 결과에 긴급도 순위가 없으면 수정 시급성·우선순위를 단정하지 마세요. 조문이 있으면 표시하세요. 한국어로 간결하게 답하세요. `[상태:]`, `[카테고리:]`, `[답변:]` 같은 메타 헤더는 출력하지 마세요. 여러 독립 항목을 함께 답할 때만 Markdown `##` 헤더로 구분하세요.
{review_signal_guide}
질문 유형: {category}
유형 지침: {instruction}
<검색된 문서>:
{context}

사용자 질문:
{question}
<이전 대화: 맥락 전용>
{history}
</이전 대화: 맥락 전용>
이전 대화는 현재 질문의 생략된 대상을 이해하기 위한 참고일 뿐입니다. 이전 질문의 답을 반복하거나, 현재 질문과 다른 주제의 답변을 앞에 붙이지 마세요. 반드시 현재 사용자 질문에만 답하세요.
"""
CATEGORY_PROMPTS = {
    QuestionCategory.CONTRACT_CONTENT: "각 항목의 사용자 조항과 표준조항 후보를 구분해 설명하세요. 질문이 포괄적이면 제공된 모든 대상의 내용을 빠뜨리지 마세요. 불이익·위험·효과를 묻지만 결과에 그 정보가 없으면 실제 영향을 판단하지 말고 제공된 표준조항 또는 사용자 조항의 내용만 설명하세요. MCP 법령 원문이 함께 제공되면 `법령 참고자료` 섹션으로 구분해 덧붙이고, 그 적용 여부나 법적 결론은 확정하지 마세요.",
    QuestionCategory.REVIEW_ANALYSIS: "조항 검토와 표준조항 누락 가능성은 반드시 구분해 답하세요. 상태와 주의 신호의 정의·목록은 제공된 검토 근거만 사용하세요.",
    QuestionCategory.REVIEW_STATUS_DEFINITION: "서버가 제공한 검토 상태의 공개 의미만 설명하세요.",
    QuestionCategory.REVIEW_RESULT_LIST: "서버가 선택한 결과 목록만 빠짐없이 정리하세요.",
    QuestionCategory.REVIEW_CLAUSE_COMPARISON: "각 조항의 사용자 원문과 표준조항 후보를 구분하여 비교하세요. 표준조항 후보가 없으면 없다고만 표시하고 이유를 추정하지 마세요.",
    QuestionCategory.REVIEW_PRIORITY: "서버가 제공한 제한 안내만 답하세요.",
    QuestionCategory.SIGNAL_SEARCH: "서버가 찾은 주의 문구 유사 신호 조항만 답하세요.",
    QuestionCategory.LEGAL_REFERENCE: "먼저 제공된 사용자 조항과 표준조항 후보를 설명하세요. MCP 조회가 완료된 법령명·조문·원문이 함께 있으면 `법령 참고자료` 섹션으로 구분해 덧붙이세요. 법령 참고자료가 없다는 안내가 있으면 그 사실만 밝히고 조항 설명은 계속하세요.",
    QuestionCategory.SERVICE_POLICY: "서비스 운영 정책은 서버가 정리한 공개 기준만 답하세요.",
}
EMPTY = "제공된 문서에서 관련 정보를 찾을 수 없습니다."
OUT_OF_SCOPE_MESSAGE = (
    "현재 질문은 계약 검토 결과·표준조항·법령 참고자료 범위를 벗어나므로 답변할 수 없습니다."
)
INSUFFICIENT_GROUNDING_MESSAGE = "현재 검토 결과에서 답변 근거를 찾지 못했습니다."
LEGAL_REFERENCE_UNAVAILABLE_MESSAGE = "연결된 법령 참고자료는 현재 검토 결과에 없습니다."
_LEGACY_META_HEADER = re.compile(
    r"^\s*(?:\[(?:상태|카테고리|답변)\s*:\s*[^\]\n]*\]\s*)+(?:\n+)?",
    re.MULTILINE,
)
DISCLAIMER = (
    "표준계약서 대비 검토 후보와 법령 참고자료에 한정하며 법률 자문이 아닙니다."
)
SERVICE_POLICY_DISCLAIMER = "서비스의 검토 결과·용어 해석 기준을 안내하며 법률 자문이 아닙니다."
STANDARD_CLAUSE_DESCRIPTION = (
    MCPStandardClause.__doc__ or "표준조항 정보"
)


def _reply(
    outcome: str, answer: str | None, refused: bool = False, **kwargs: object
) -> ChatResponse:
    disclaimer = str(kwargs.pop("disclaimer", DISCLAIMER))
    return ChatResponse(
        outcome=outcome,
        answer=answer,
        refused=refused,
        tool_status="NOT_REQUESTED",
        disclaimer=disclaimer,
        **kwargs,
    )


def _refusal(reason: ChatRefusalReason) -> ChatResponse:
    """모델 본문과 분리한 고정 제한 사유를 반환한다."""
    message = (
        OUT_OF_SCOPE_MESSAGE
        if reason is ChatRefusalReason.OUT_OF_SCOPE
        else INSUFFICIENT_GROUNDING_MESSAGE
    )
    return _reply(
        "REFUSED",
        None,
        True,
        refusal_reason=reason,
        limitations=[message],
    )


def _normalize_answer(text: str) -> str:
    """모델이 생성한 레거시 메타 헤더와 중복된 정형 거절 문구만 제거한다."""
    normalized = _LEGACY_META_HEADER.sub("", text.strip()).strip()
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
    if len(paragraphs) > 1:
        paragraphs = [part for part in paragraphs if part != EMPTY]
    return "\n\n".join(paragraphs).strip()


def _with_plan_notice(answer: str, plan: AnswerPlan) -> str:
    """법령 원문 조회 실패는 조항 설명을 막지 않고 고정 안내만 덧붙인다."""
    if not plan.legal_reference_notice:
        return answer
    return f"{answer.rstrip()}\n\n{plan.legal_reference_notice}"


def _service_policy_response(payload: ChatRequest) -> ChatResponse | None:
    """기존 공개 상태 정의만 사용하는 일반 운영 정책 답변을 만든다."""
    if payload.focus_clause_id or referenced_article_numbers(payload.message):
        return None
    normalized = payload.message.replace(" ", "")
    topic: str | None = None
    if "표준조항" in normalized and any(word in normalized for word in ("무엇", "뭐", "뜻")):
        topic = "STANDARD"
    elif "별도확인" in normalized and any(word in normalized for word in ("어떻게", "선정", "기준", "뜻")):
        topic = "EXTRA"
    elif any(word in normalized for word in ("검색후보", "NO_MATCH")):
        topic = "NO_MATCH"
    elif any(word in normalized for word in ("누락", "MISSING")):
        topic = "MISSING"
    elif any(word in normalized for word in ("주의신호", "주의문구", "toxic_patterns")):
        topic = "TOXIC"
    if topic is None:
        return None
    if topic == "STANDARD":
        answer = f"{STANDARD_CLAUSE_DESCRIPTION}는 계약서 내용을 비교할 때 함께 확인하는 기준 정보입니다. 표준조항 후보가 있다는 사실만으로 안전성이나 적법성을 판단하지 않습니다."
    elif topic == "TOXIC":
        answer = f"{TOXIC_PATTERNS_DESCRIPTION}은 표준 대비 상태와 독립적인 보조 신호입니다. 신호가 있거나 없다는 사실만으로 법률적 판단을 하지 않습니다."
    else:
        answer = f"**{RESULT_CODE_LABELS[topic]}**\n\n{RESULT_CODE_DESCRIPTIONS[topic]}"
    return _reply(
        "ANSWERED",
        answer,
        disclaimer=SERVICE_POLICY_DISCLAIMER,
        question_category=QuestionCategory.SERVICE_POLICY.value,
    )


def _toxic_signal_labels(review: Review, item: dict[str, Any]) -> list[str]:
    """검토 시점에 보관한 MCP title만 반환하고 내부 코드는 숨긴다."""
    snapshot = review.result.get("toxic_pattern_labels", {}) if review.result else {}
    if not isinstance(snapshot, dict):
        return []
    raw_codes = item.get("toxic_patterns")
    if not isinstance(raw_codes, list):
        return []
    return [
        label
        for code in raw_codes
        if isinstance(code, str)
        and isinstance((label := snapshot.get(code)), str)
        and label
    ]


def _is_signal_question(message: str) -> bool:
    normalized = message.replace(" ", "")
    return any(word in normalized for word in ("주의신호", "주의문구", "toxic_patterns")) and any(
        word in normalized for word in ("왜", "이유", "무엇", "뭐")
    )


def _is_review_wide_signal_question(message: str) -> bool:
    """특정 조항이 아닌 계약서 전체의 기록된 신호를 묻는지 판별한다."""
    normalized = message.replace(" ", "")
    return any(word in normalized for word in ("제계약서", "계약서의", "계약서에", "전체", "전부", "모든조항"))


def _signal_attribution_response(
    review: Review,
    payload: ChatRequest,
    focused: dict[str, Any] | None,
) -> ChatResponse | None:
    """특정 조항의 신호 귀속을 모델 추정 없이 그대로 설명한다."""
    normalized = payload.message.replace(" ", "")
    has_signal_term = any(
        word in normalized for word in ("주의신호", "주의문구", "toxic_patterns")
    )
    review_wide = _is_review_wide_signal_question(payload.message)
    has_clause_target = bool(focused or referenced_article_numbers(payload.message))
    if not _is_signal_question(payload.message) and not (
        has_signal_term and (review_wide or has_clause_target)
    ):
        return None
    targets = [focused] if focused else [
        item
        for item in clause_results(review.result)
        if clause_article_number(item) in referenced_article_numbers(payload.message)
    ]
    review_wide = not targets and review_wide
    if review_wide:
        targets = [
            item
            for item in clause_results(review.result)
            if isinstance(item.get("toxic_patterns"), list) and item["toxic_patterns"]
        ]
    if not targets:
        if review_wide:
            return _reply(
                "ANSWERED",
                f"현재 검토 결과에는 기록된 {TOXIC_PATTERNS_DESCRIPTION}가 있는 조항이 없습니다. 이는 안전성이나 적법성 판단이 아닙니다.",
                question_category=QuestionCategory.REVIEW_ANALYSIS.value,
            )
        return None
    sections: list[str] = []
    for item in targets:
        clause = clause_display_label(item.get("user_clause")) or "선택한 조항"
        raw_signals = item.get("toxic_patterns")
        has_signals = isinstance(raw_signals, list) and bool(raw_signals)
        labels = _toxic_signal_labels(review, item)
        if labels:
            sections.append(
                f"## {clause}\n\n이 조항의 검토 결과에 연결된 {TOXIC_PATTERNS_DESCRIPTION}: "
                + ", ".join(labels)
                + "\n\n신호별 탐지 이유나 다른 조항과의 관계는 제공된 검토 결과에 포함되어 있지 않습니다."
            )
        elif has_signals:
            sections.append(
                f"## {clause}\n\n이 조항의 검토 결과에 {TOXIC_PATTERNS_DESCRIPTION}가 포함되어 있습니다. 다만 기존 표시 라벨을 확인할 수 없어 개별 코드값은 표시하지 않습니다. 신호별 탐지 이유는 제공되지 않았습니다."
            )
        else:
            sections.append(
                f"## {clause}\n\n이 조항의 검토 결과에는 {TOXIC_PATTERNS_DESCRIPTION}가 포함되어 있지 않습니다. 이는 안전성이나 적법성 판단이 아닙니다."
            )
    return _reply(
        "ANSWERED",
        "\n\n".join(sections),
        sources=[source for item in targets if (source := _user_source(item))],
        question_category=(
            QuestionCategory.REVIEW_ANALYSIS.value
            if review_wide
            else QuestionCategory.CONTRACT_CONTENT.value
        ),
    )


def _review_intent_response(review: Review, payload: ChatRequest) -> ChatResponse | None:
    """목록·상태 의미·우선순위처럼 모델 추정이 필요 없는 질문을 처리한다."""
    normalized = payload.message.replace(" ", "")
    if any(word in normalized for word in ("수정시급", "시급한", "긴급도", "우선순위")):
        return _reply(
            "ANSWERED",
            "MCP 결과에는 수정 시급성이나 우선순위 정보가 없어 특정 조항의 우선순위를 단정할 수 없습니다.",
            question_category=QuestionCategory.REVIEW_PRIORITY.value,
        )
    codes = _mentioned_result_codes(payload.message)
    is_definition = any(word in normalized for word in ("무슨뜻", "무엇", "뭐", "의미"))
    if len(codes) == 1 and is_definition:
        code = codes[0]
        return _reply(
            "ANSWERED",
            f"**{RESULT_CODE_LABELS[code]}**\n\n{RESULT_CODE_DESCRIPTIONS[code]}",
            question_category=QuestionCategory.REVIEW_STATUS_DEFINITION.value,
        )
    has_all = any(word in normalized for word in ("전부", "모두", "목록", "몇개"))
    is_list = has_all and any(word in normalized for word in ("알려", "목록", "몇개")) and not any(
        word in normalized for word in ("설명", "비교")
    )
    if len(codes) != 1 or not is_list:
        return None
    code = codes[0]
    if code == "MISSING":
        items = [item for item in review.result.get("missing_standard_clauses", []) if isinstance(item, dict)]
        sources = [source for item in items if (source := _missing_source(item))]
        labels = [(standard_clause(item) or {}).get("title") for item in items]
    else:
        items = [item for item in clause_results(review.result) if item.get("deviation") == code]
        sources = [source for item in items if (source := _user_source(item))]
        labels = [clause_display_label(item.get("user_clause")) for item in items]
    display_labels = [label for label in labels if isinstance(label, str) and label]
    if not display_labels:
        return _refusal(ChatRefusalReason.INSUFFICIENT_GROUNDING).model_copy(
            update={"question_category": QuestionCategory.REVIEW_RESULT_LIST.value}
        )
    answer = f"**{RESULT_CODE_LABELS[code]} 조항 {len(display_labels)}개**\n\n" + "\n".join(
        f"- {label}" for label in display_labels
    )
    return _reply(
        "ANSWERED",
        answer,
        sources=_dedupe_sources(sources),
        question_category=QuestionCategory.REVIEW_RESULT_LIST.value,
    )


def _signal_search_response(review: Review, payload: ChatRequest) -> ChatResponse | None:
    """질문어와 기존 주의 신호 라벨이 겹치는 사용자 조항만 찾는다."""
    normalized = payload.message.replace(" ", "")
    if not any(word in normalized for word in ("뉘앙스", "주의신호", "추가업무", "업무지시")):
        return None
    query_terms = tuple(term for term in ("추가", "업무", "지시", "해석", "손해", "해지", "비밀") if term in normalized)
    if not query_terms:
        return None
    matched: list[dict[str, Any]] = []
    for item in clause_results(review.result):
        labels = _toxic_signal_labels(review, item)
        if any(sum(term in label.replace(" ", "") for term in query_terms) >= 2 for label in labels):
            matched.append(item)
    if not matched:
        return None
    sections = []
    for item in matched:
        clause = clause_display_label(item.get("user_clause")) or "조항 식별자 없음"
        labels = ", ".join(_toxic_signal_labels(review, item))
        sections.append(f"## {clause}\n\n- {TOXIC_PATTERNS_DESCRIPTION}: {labels}\n- 사용자 조항: {item.get('user_clause')}")
    return _reply(
        "ANSWERED",
        "\n\n".join(sections),
        sources=[source for item in matched if (source := _user_source(item))],
        question_category=QuestionCategory.SIGNAL_SEARCH.value,
    )


def _review_intent_category(payload: ChatRequest) -> QuestionCategory | None:
    """비교 질문은 결과군 선택 뒤 LLM이 항목별 설명만 하도록 분리한다."""
    normalized = payload.message.replace(" ", "")
    if "비교" in normalized or "표준과" in normalized:
        return QuestionCategory.REVIEW_CLAUSE_COMPARISON
    return None


def _ambiguous_follow_up_category(
    payload: ChatRequest, conversation_context: ChatContextState | None
) -> QuestionCategory | None:
    """직전 결과군을 가리키는 짧은 후속 질문은 표준조항 설명으로 좁힌다."""
    if not conversation_context or _has_explicit_target(payload.message):
        return None
    normalized = payload.message.replace(" ", "")
    if any(word in normalized for word in ("불이익", "위험", "문제", "영향", "효과")):
        return QuestionCategory.CONTRACT_CONTENT
    return None


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
        raise _llm_error(error, operation="답변 생성") from error
    return str(getattr(result, "content", "")).strip()


async def _classify_question(
    model: BaseChatModel,
    prompt: str,
    timeout: float,
) -> QuestionCategory | None:
    """JSON Schema 분류 결과를 검증하며 파싱 실패는 안전하게 거부한다."""
    try:
        structured_model = model.with_structured_output(
            RouterDecision,
            method="json_schema",
            include_raw=True,
        )
        result = await asyncio.wait_for(
            structured_model.ainvoke([HumanMessage(content=prompt)]),
            timeout=timeout,
        )
    except (TimeoutError, asyncio.TimeoutError) as error:
        raise ExternalServiceTimeoutError(
            code="LLM_TIMEOUT",
            message="질문 분류 시간이 초과되었습니다.",
            retryable=True,
            next_action="RETRY",
        ) from error
    except ConnectionError as error:
        raise ExternalServiceError(
            code="LLM_CONNECTION_FAILED",
            message="질문 분류 서비스에 연결하지 못했습니다.",
            retryable=True,
            next_action="RETRY",
        ) from error
    except Exception as error:
        raise _llm_error(error, operation="질문 분류") from error

    if not isinstance(result, dict) or result.get("parsing_error") is not None:
        return None
    parsed = result.get("parsed")
    if isinstance(parsed, RouterDecision):
        return parsed.category
    try:
        return RouterDecision.model_validate(parsed).category
    except ValidationError:
        return None


def _llm_error(
    error: Exception, *, operation: str
) -> ExternalServiceConfigurationError | ExternalServiceError | OverCapacityError:
    """공급자 오류를 원인별 API 오류로 정규화하되 원문은 노출하지 않는다."""
    status_code = getattr(error, "status_code", None)
    if status_code in {400, 401, 403, 404}:
        code = (
            "LLM_AUTH_FAILED"
            if status_code in {401, 403}
            else "LLM_CONFIGURATION_INVALID"
        )
        return ExternalServiceConfigurationError(
            code=code,
            message=f"{operation} 모델 설정을 확인해 주세요.",
            details={"upstream_status": status_code},
        )
    if status_code == 429:
        return OverCapacityError(
            code="LLM_RATE_LIMITED",
            message=f"{operation} 요청이 일시적으로 많습니다.",
            retry_after_seconds=5,
        )
    if isinstance(status_code, int) and status_code >= 500:
        return ExternalServiceError(
            code="LLM_UPSTREAM_UNAVAILABLE",
            message=f"{operation} 서비스가 일시적으로 응답하지 않습니다.",
            retryable=True,
            next_action="RETRY",
            details={"upstream_status": status_code},
        )
    return ExternalServiceError(
        code="LLM_OUTPUT_INVALID",
        message=f"{operation} 결과를 처리하지 못했습니다.",
        retryable=False,
    )

def _mentioned_result_codes(message: str) -> tuple[str, ...]:
    normalized = message.replace(" ", "")
    codes: list[str] = []
    for code, words in {
        "EXTRA": ("별도확인", "추가확인"),
        "NO_MATCH": ("검색후보없음", "검색후보가없", "대응후보없음", "대응후보가없", "NO_MATCH"),
        "MISSING": ("누락", "MISSING"),
    }.items():
        if any(word in normalized for word in words):
            codes.append(code)
    return tuple(codes)


def _has_explicit_target(message: str) -> bool:
    return bool(referenced_article_numbers(message) or _mentioned_result_codes(message))


def _continuation_category(
    payload: ChatRequest, conversation_context: ChatContextState | None
) -> QuestionCategory | None:
    """이어보기 요청은 이미 확정한 질문 유형을 재사용한다."""
    if not conversation_context or not (conversation_context.next_segment_offset or 0) > 0:
        return None
    normalized = payload.message.replace(" ", "")
    if not any(word in normalized for word in ("이어서", "계속답변", "계속설명")):
        return None
    try:
        return QuestionCategory(conversation_context.category)
    except ValueError:
        return None


def _user_source(item: dict[str, Any]) -> ChatSource | None:
    identifier = user_clause_id(item)
    if not identifier:
        return None
    return ChatSource(
        type="USER_CLAUSE",
        id=identifier,
        display_label=clause_display_label(item.get("user_clause")),
    )


def _missing_source(item: dict[str, Any]) -> ChatSource | None:
    standard = standard_clause(item) or {}
    identifier = standard.get("clause_id")
    title = standard.get("title")
    if not isinstance(identifier, str) and not isinstance(title, str):
        return None
    return ChatSource(
        type="STANDARD_CLAUSE",
        id=identifier if isinstance(identifier, str) else None,
        display_label=title if isinstance(title, str) else "표준조항 누락 가능성",
        standard_contract_label=standard.get("standard_contract_label"),
    )


def _user_item(review: Review, item: dict[str, Any]) -> AnswerPlanItem:
    standard = standard_clause(item) or {}
    signal_labels = _toxic_signal_labels(review, item)
    raw_signals = item.get("toxic_patterns")
    has_signals = isinstance(raw_signals, list) and bool(raw_signals)
    lines = [
        f"조항: {clause_display_label(item.get('user_clause')) or '조항 식별자 없음'}",
        f"사용자 조항 원문: {item.get('user_clause') or '제공되지 않음'}",
        f"검토 상태: {RESULT_CODE_LABELS.get(str(item.get('deviation')), str(item.get('deviation') or '확인 필요'))}",
        f"표준조항 후보: {standard.get('title') or '제공되지 않음'}",
    ]
    if standard.get("text"):
        lines.append(f"표준조항 원문: {standard['text']}")
    if signal_labels:
        lines.append(f"주의 문구 유사 신호: {', '.join(signal_labels)}")
    elif has_signals:
        lines.append(f"주의 문구 유사 신호: {TOXIC_PATTERNS_DESCRIPTION}")
    else:
        lines.append("주의 문구 유사 신호: 없음")
    source = _user_source(item)
    return AnswerPlanItem(
        kind="USER_CLAUSE",
        identifier=user_clause_id(item) or clause_display_label(item.get("user_clause")) or "user-clause",
        context="\n".join(lines),
        sources=(source,) if source else (),
    )


def _missing_item(item: dict[str, Any]) -> AnswerPlanItem:
    standard = standard_clause(item) or {}
    lines = [
        f"표준조항 누락 가능성: {standard.get('title') or '항목 식별자 없음'}",
        f"표준조항 원문: {standard.get('text') or '제공되지 않음'}",
        "이 항목은 계약서 전체에서 대응 내용을 찾지 못한 표준조항 후보이며 사용자 조항 결과와 구분합니다.",
    ]
    source = _missing_source(item)
    return AnswerPlanItem(
        kind="MISSING_STANDARD_CLAUSE",
        identifier=str(standard.get("clause_id") or standard.get("title") or "missing-standard"),
        context="\n".join(lines),
        sources=(source,) if source else (),
    )


def _filter_plan_items(
    review: Review,
    payload: ChatRequest,
    focused: dict[str, Any] | None,
    conversation_context: ChatContextState | None,
) -> tuple[str, tuple[str, ...], list[dict[str, Any]], list[dict[str, Any]]]:
    users = clause_results(review.result)
    missing = [item for item in review.result.get("missing_standard_clauses", []) if isinstance(item, dict)]
    explicit_codes = _mentioned_result_codes(payload.message)
    article_numbers = referenced_article_numbers(payload.message)
    if focused:
        return "SINGLE_CLAUSE", (), [focused], []
    if article_numbers:
        return "SINGLE_CLAUSE", (), [item for item in users if clause_article_number(item) in article_numbers], []
    if explicit_codes:
        if "MISSING" in explicit_codes:
            return "MISSING_STANDARD_CLAUSES", ("MISSING",), [], missing
        return "RESULT_GROUP", explicit_codes, [item for item in users if item.get("deviation") in explicit_codes], []
    if conversation_context:
        if conversation_context.target_kind is ChatContextTargetKind.SINGLE_CLAUSE:
            selected = [item for item in users if user_clause_id(item) in conversation_context.selected_clause_ids]
            return "SINGLE_CLAUSE", (), selected, []
        if conversation_context.target_kind is ChatContextTargetKind.MISSING_STANDARD_CLAUSES:
            selected = [
                item for item in missing
                if (standard_clause(item) or {}).get("clause_id") in conversation_context.missing_standard_clause_ids
            ]
            return "MISSING_STANDARD_CLAUSES", ("MISSING",), [], selected or missing
        if conversation_context.target_kind is ChatContextTargetKind.RESULT_GROUP:
            codes = tuple(conversation_context.result_codes)
            return "RESULT_GROUP", codes, [item for item in users if item.get("deviation") in codes], []
    return "REVIEW_ALL", (), users, missing


def _requires_explicit_law_source(message: str) -> bool:
    """법령 원문 자체를 요구한 경우에만 조항 설명 폴백을 제한한다."""
    normalized = message.replace(" ", "")
    if any(marker in normalized for marker in ("법령원문", "법조문", "법률조문", "법령명")):
        return True
    return bool(
        re.search(
            r"(?:민법|상법|저작권법|근로기준법|개인정보보호법|하도급법|정보통신망법)\s*제?\d+조",
            normalized,
        )
    )


def _is_signal_impact_question(
    category: QuestionCategory,
    message: str,
    users: list[dict[str, Any]],
) -> bool:
    """기록된 주의 신호의 의미·영향을 묻는 조항 질문만 법령 원문을 조회한다."""
    if category is not QuestionCategory.CONTRACT_CONTENT:
        return False
    has_recorded_signal = any(
        isinstance(item.get("toxic_patterns"), list) and item["toxic_patterns"]
        for item in users
    )
    if not has_recorded_signal:
        return False
    normalized = message.replace(" ", "")
    return any(
        term in normalized
        for term in ("문제", "불이익", "위험", "영향", "효과", "확인", "어떻게해야")
    )


def _law_plan_items(grounds: list[Any]) -> list[AnswerPlanItem]:
    """OK 상태의 MCP 법령 원문만 채팅 답변 계획에 추가한다."""
    items: list[AnswerPlanItem] = []
    for ground in grounds:
        if ground.grounding_status != GroundingStatus.OK:
            continue
        for law in ground.items:
            source = ChatSource(
                type="LAW",
                id=law.source_id,
                display_label=" ".join(filter(None, (law.law_name, law.article))),
                law_name=law.law_name,
                article=law.article,
                source_url=law.source_url,
            )
            items.append(
                AnswerPlanItem(
                    "LAW",
                    law.source_id,
                    f"법령 참고자료: {law.law_name or ''} {law.article or ''}\n원문: {law.text}",
                    (source,),
                )
            )
    return items


async def _build_answer_plan(
    category: QuestionCategory,
    review: Review,
    payload: ChatRequest,
    focused: dict[str, Any] | None,
    runtime: WorkShieldMCPRuntime,
    settings: Settings,
    conversation_context: ChatContextState | None,
) -> AnswerPlan:
    target_kind, result_codes, users, missing = _filter_plan_items(
        review, payload, focused, conversation_context
    )
    contract_items = [_user_item(review, item) for item in users] + [_missing_item(item) for item in missing]
    should_attach_grounding = (
        category is QuestionCategory.LEGAL_REFERENCE
        or _is_signal_impact_question(category, payload.message, users)
    )
    if should_attach_grounding:
        categories = list(dict.fromkeys(filter(None, (clause_category(item) for item in users))))
        grounds = await asyncio.gather(
            *(get_review_grounding(review, value, runtime, settings) for value in categories)
        )
        law_items = _law_plan_items(list(grounds))
        if law_items:
            return AnswerPlan(target_kind, result_codes, tuple([*contract_items, *law_items]))
        if contract_items and not (
            category is QuestionCategory.LEGAL_REFERENCE
            and _requires_explicit_law_source(payload.message)
        ):
            return AnswerPlan(
                target_kind,
                result_codes,
                tuple(contract_items),
                legal_reference_notice=LEGAL_REFERENCE_UNAVAILABLE_MESSAGE,
            )
        return AnswerPlan("LEGAL_REFERENCE", (), ())
    return AnswerPlan(target_kind, result_codes, tuple(contract_items))


def answer_plan_context(
    review: Review,
    payload: ChatRequest,
    question_category: str | None,
    *,
    conversation_context: ChatContextState | None = None,
) -> dict[str, object]:
    """답변 원문 대신 다음 질문에 적용할 결과 대상만 저장한다."""
    focused = find_user_clause(review.result, payload.focus_clause_id) if payload.focus_clause_id else None
    kind, codes, users, missing = _filter_plan_items(review, payload, focused, conversation_context)
    target_kind = ChatContextTargetKind(kind)
    return {
        "category": question_category or "UNKNOWN",
        "target_kind": target_kind,
        "selected_clause_ids": [user_clause_id(item) for item in users if user_clause_id(item)],
        "result_codes": list(codes),
        "missing_standard_clause_ids": [str((standard_clause(item) or {}).get("clause_id")) for item in missing if (standard_clause(item) or {}).get("clause_id")],
        "answer_scope": "clause" if target_kind is ChatContextTargetKind.SINGLE_CLAUSE else "review",
    }


def _segment_prompt(category: QuestionCategory, payload: ChatRequest, items: tuple[AnswerPlanItem, ...]) -> str:
    context = "\n\n---\n\n".join(item.context for item in items)
    return BASE_PROMPT.format(
        category=category.value,
        instruction=CATEGORY_PROMPTS[category] + " 이 묶음의 항목만 빠짐없이 답하고 각 항목을 `##` 제목으로 시작하세요. 다른 묶음의 서론·면책·근거 부족 문구는 반복하지 마세요.",
        review_signal_guide=REVIEW_SIGNAL_GUIDE,
        context=context,
        question=payload.message,
        history="대화 원문은 저장하거나 답변 근거로 사용하지 않습니다.",
    )


async def _prompt_tokens(prompt: str, settings: Settings) -> int:
    """운영 vLLM tokenizer로 prompt를 세고, 실패 시 안전한 문자 상한을 쓴다."""
    if settings.app_env == "prod" and settings.vllm_base_url and settings.llm_model:
        url = f"{str(settings.vllm_base_url).rstrip('/')}/tokenize"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(url, json={"model": settings.llm_model, "prompt": prompt})
                response.raise_for_status()
                data = response.json()
            tokens = data.get("tokens") or data.get("token_ids")
            if isinstance(tokens, list):
                return len(tokens)
        except (httpx.HTTPError, ValueError, TypeError):
            pass
    # Korean 계약 원문은 문자 수보다 token 수가 커지기 어렵기 때문에 과소추정하지 않는다.
    return len(prompt)


def _split_large_item(item: AnswerPlanItem) -> list[AnswerPlanItem]:
    """단일 조항도 한도를 넘으면 원문을 버리지 않고 문단 단위로 나눈다."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", item.context) if part.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [item.context[index:index + 3_000] for index in range(0, len(item.context), 3_000)]
    return [
        AnswerPlanItem(item.kind, f"{item.identifier}:{index}", paragraph, item.sources)
        for index, paragraph in enumerate(paragraphs, start=1)
    ]


async def _token_aware_segments(
    category: QuestionCategory,
    payload: ChatRequest,
    items: tuple[AnswerPlanItem, ...],
    offset: int,
    settings: Settings,
) -> list[tuple[AnswerPlanItem, ...]]:
    """3개 항목과 Qwen 7,104-token prompt 예산을 함께 적용한다."""
    pending = list(items[offset:])
    segments: list[tuple[AnswerPlanItem, ...]] = []
    current: list[AnswerPlanItem] = []
    while pending:
        candidate = pending.pop(0)
        proposed = tuple([*current, candidate])
        within_count = len(proposed) <= ANSWER_SEGMENT_SIZE
        within_tokens = await _prompt_tokens(_segment_prompt(category, payload, proposed), settings) <= MAX_PROMPT_TOKENS
        if within_count and within_tokens:
            current.append(candidate)
            continue
        if current:
            segments.append(tuple(current))
            current = []
            pending.insert(0, candidate)
            continue
        pieces = _split_large_item(candidate)
        if len(pieces) == 1:
            # 원문은 보존하고 provider가 명확한 context-limit 오류를 반환하게 한다.
            segments.append((candidate,))
        else:
            pending[0:0] = pieces
    if current:
        segments.append(tuple(current))
    return segments


def _dedupe_sources(items: list[ChatSource]) -> list[ChatSource]:
    result: list[ChatSource] = []
    seen: set[tuple[object, ...]] = set()
    for source in items:
        key = (source.type, source.id, source.display_label, source.law_name, source.article)
        if key not in seen:
            seen.add(key)
            result.append(source)
    return result


async def _classify(
    review: Review,
    payload: ChatRequest,
    router_model: BaseChatModel,
    settings: Settings,
    llm_policy: LLMPolicy,
) -> QuestionCategory | None:
    started_at = perf_counter()
    category: QuestionCategory | None = None
    state = "failed"
    try:
        category = await _classify_question(
            router_model,
            ROUTER_PROMPT.format(question=payload.message),
            min(settings.router_llm_timeout_seconds, llm_policy.timeout_seconds),
        )
        state = "parsed" if category else "invalid"
        return category
    finally:
        log_event(event="chat.router.completed", review_id=review.id, category=category.value if category else None, state=state, duration_ms=round((perf_counter() - started_at) * 1000, 2))


async def answer_review_question(
    review: Review,
    payload: ChatRequest,
    *,
    runtime: WorkShieldMCPRuntime,
    router_model: BaseChatModel,
    model: BaseChatModel,
    settings: Settings,
    llm_policy: LLMPolicy = DEFAULT_LLM_POLICY,
    conversation_context: ChatContextState | None = None,
) -> ChatResponse:
    if review.state is not ReviewState.COMPLETED or not review.result:
        raise ConflictError(code="REVIEW_NOT_COMPLETED", message="완료된 검토에서만 질문할 수 있습니다.")
    focused = find_user_clause(review.result, payload.focus_clause_id) if payload.focus_clause_id else None
    if payload.focus_clause_id and focused is None:
        raise AppValidationError(code="FOCUS_CLAUSE_NOT_FOUND", message="현재 검토 결과에 없는 조항입니다.", field="focus_clause_id")
    if signal_response := _signal_attribution_response(review, payload, focused):
        return signal_response
    if search_response := _signal_search_response(review, payload):
        return search_response
    if intent_response := _review_intent_response(review, payload):
        return intent_response
    if policy_response := _service_policy_response(payload):
        return policy_response
    category = (
        _continuation_category(payload, conversation_context)
        or _ambiguous_follow_up_category(payload, conversation_context)
        or _review_intent_category(payload)
        or await _classify(
        review, payload, router_model, settings, llm_policy
        )
    )
    if category is None:
        return _reply("LLM_OUTPUT_INVALID", None, True, limitations=["질문 유형을 분류하지 못했습니다."])
    if category is QuestionCategory.OUT_OF_SCOPE:
        return _refusal(ChatRefusalReason.OUT_OF_SCOPE).model_copy(update={"question_category": category.value})
    plan = await _build_answer_plan(category, review, payload, focused, runtime, settings, conversation_context)
    if not plan.items:
        return _refusal(ChatRefusalReason.INSUFFICIENT_GROUNDING).model_copy(update={"question_category": category.value})
    offset = conversation_context.next_segment_offset if conversation_context else 0
    answers: list[str] = []
    sources: list[ChatSource] = []
    for segment in await _token_aware_segments(category, payload, plan.items, offset or 0, settings):
        text = _normalize_answer(await _invoke(model, _segment_prompt(category, payload, segment), llm_policy.timeout_seconds))
        if text:
            answers.append(text)
        sources.extend(source for item in segment for source in item.sources)
    if not answers:
        return _reply("LLM_OUTPUT_INVALID", None, True, limitations=["답변을 생성하지 못했습니다."], question_category=category.value)
    return _reply(
        "ANSWERED",
        _with_plan_notice("\n\n".join(answers), plan),
        sources=_dedupe_sources(sources),
        question_category=category.value,
    )


async def stream_review_answer(
    review: Review,
    payload: ChatRequest,
    *,
    runtime: WorkShieldMCPRuntime,
    router_model: BaseChatModel,
    model: BaseChatModel,
    settings: Settings,
    llm_policy: LLMPolicy = DEFAULT_LLM_POLICY,
    conversation_context: ChatContextState | None = None,
) -> AsyncIterator[tuple[str, object]]:
    if review.state is not ReviewState.COMPLETED or not review.result:
        raise ConflictError(code="REVIEW_NOT_COMPLETED", message="완료된 검토에서만 질문할 수 있습니다.")
    focused = find_user_clause(review.result, payload.focus_clause_id) if payload.focus_clause_id else None
    if payload.focus_clause_id and focused is None:
        raise AppValidationError(code="FOCUS_CLAUSE_NOT_FOUND", message="현재 검토 결과에 없는 조항입니다.", field="focus_clause_id")
    yield "progress", {"stage": "UNDERSTANDING_REQUEST", "message": "질문 범위를 확인하고 있습니다."}
    if signal_response := _signal_attribution_response(review, payload, focused):
        yield "completed", signal_response
        return
    if search_response := _signal_search_response(review, payload):
        yield "completed", search_response
        return
    if intent_response := _review_intent_response(review, payload):
        yield "completed", intent_response
        return
    if policy_response := _service_policy_response(payload):
        yield "completed", policy_response
        return
    category = (
        _continuation_category(payload, conversation_context)
        or _ambiguous_follow_up_category(payload, conversation_context)
        or _review_intent_category(payload)
        or await _classify(
        review, payload, router_model, settings, llm_policy
        )
    )
    if category is None:
        yield "completed", _reply("LLM_OUTPUT_INVALID", None, True, limitations=["질문 유형을 분류하지 못했습니다."], question_category=None)
        return
    if category is QuestionCategory.OUT_OF_SCOPE:
        yield "completed", _refusal(ChatRefusalReason.OUT_OF_SCOPE).model_copy(update={"question_category": category.value})
        return
    yield "progress", {"stage": "PREPARING_EVIDENCE", "message": "질문 유형에 맞는 검토 근거를 준비하고 있습니다.", "category": category.value}
    plan = await _build_answer_plan(category, review, payload, focused, runtime, settings, conversation_context)
    if not plan.items:
        yield "completed", _refusal(ChatRefusalReason.INSUFFICIENT_GROUNDING).model_copy(update={"question_category": category.value})
        return
    offset = conversation_context.next_segment_offset if conversation_context else 0
    segments = await _token_aware_segments(category, payload, plan.items, offset or 0, settings)
    answers: list[str] = []
    all_sources: list[ChatSource] = []
    consumed_offset = offset or 0
    for index, segment in enumerate(segments, start=1):
        marker = {"index": index, "total": len(segments)}
        yield "progress", {"stage": "COMPOSING_RESPONSE", "message": "답변을 작성하고 있습니다.", "category": category.value, "segment": marker}
        prompt = _segment_prompt(category, payload, segment)
        chunks: list[str] = []
        try:
            try:
                async for chunk in model.astream([HumanMessage(content=prompt)]):
                    text = str(getattr(chunk, "content", ""))
                    if text:
                        chunks.append(text)
                        yield "delta", {"text": text, "segment": marker}
            except (AttributeError, NotImplementedError):
                text = await _invoke(model, prompt, llm_policy.timeout_seconds)
                if text:
                    chunks.append(text)
                    yield "delta", {"text": text, "segment": marker}
        except Exception as error:
            yield "failed", {"error": {"code": getattr(error, "code", "CHAT_STREAM_FAILED"), "message": getattr(error, "message", "답변 묶음을 생성하지 못했습니다."), "retryable": bool(getattr(error, "retryable", False)), "next_action": getattr(error, "next_action", None)}, "partial_answer_available": bool(answers), "continuation": {"next_segment_offset": consumed_offset, "remaining_segments": len(segments) - index + 1}, "question_category": category.value}
            return
        answer = _normalize_answer("".join(chunks))
        if answer:
            answers.append(answer)
        segment_sources = [source for item in segment for source in item.sources]
        all_sources.extend(segment_sources)
        yield "segment_complete", {"segment": marker, "sources": _dedupe_sources(segment_sources)}
        consumed_offset += len(segment)
    if answers and plan.legal_reference_notice:
        answers.append(plan.legal_reference_notice)
        yield "delta", {"text": f"\n\n{plan.legal_reference_notice}", "segment": None}
    yield "progress", {"stage": "DELIVERING_RESPONSE", "message": "답변과 출처를 정리하고 있습니다.", "category": category.value}
    response = _reply("ANSWERED", "\n\n".join(answers), sources=_dedupe_sources(all_sources), question_category=category.value) if answers else _reply("LLM_OUTPUT_INVALID", None, True, limitations=["답변을 생성하지 못했습니다."], question_category=category.value)
    yield "completed", response
