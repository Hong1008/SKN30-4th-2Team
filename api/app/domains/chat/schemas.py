"""Chat API 공개 DTO."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ChatOutcome(StrEnum):
    """질의응답 결과 유형."""

    ANSWERED = "ANSWERED"
    REFUSED = "REFUSED"
    INSUFFICIENT_GROUNDING = "INSUFFICIENT_GROUNDING"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"


class ChatRefusalReason(StrEnum):
    """답변 제한의 사용자 공개 사유."""

    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    INSUFFICIENT_GROUNDING = "INSUFFICIENT_GROUNDING"


class ChatSourceType(StrEnum):
    """참조 근거 유형."""

    USER_CLAUSE = "USER_CLAUSE"
    STANDARD_CLAUSE = "STANDARD_CLAUSE"
    LAW = "LAW"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000, description="사용자 질문 본문")
    focus_clause_id: str | None = Field(default=None, max_length=128, description="UI에서 선택한 사용자 조항 ID")
    history: list[dict[str, str]] = Field(
        default_factory=list,
        max_length=2,
        description="호환 기간에만 허용하는 최근 대화 발췌",
    )
    conversation_token: str | None = Field(default=None, max_length=128, description="직전 답변의 원문 없는 후속 질문 상태 토큰")


class ChatSource(BaseModel):
    type: ChatSourceType = Field(description="출처 유형 코드")
    id: str | None = Field(default=None, description="출처 식별자")
    display_label: str | None = Field(default=None, description="사용자에게 표시할 출처명")
    standard_contract_label: str | None = Field(default=None, description="표준계약서 표시명")
    law_name: str | None = Field(default=None, description="법령명")
    article: str | None = Field(default=None, description="법령 조문")
    source_url: str | None = Field(default=None, description="공개 법령 원문 주소")


class ChatResponse(BaseModel):
    outcome: ChatOutcome = Field(description="답변 처리 결과 코드")
    answer: str | None = Field(default=None, description="검토 근거에 한정한 답변 본문")
    refused: bool = Field(description="근거 부족 또는 범위 밖으로 답변을 제한했는지 여부")
    refusal_reason: ChatRefusalReason | None = Field(
        default=None,
        description="답변 제한 시 사용자에게 공개할 제한 사유 코드",
    )
    sources: list[ChatSource] = Field(default_factory=list, description="답변에 사용한 사용자 조항·법령 출처")
    limitations: list[str] = Field(default_factory=list, description="답변을 만들지 못한 경우의 제한 사유")
    tool_status: str = Field(description="법령 근거 조회 상태 코드")
    disclaimer: str = Field(description="법률 자문이 아니라는 고지")
    conversation_token: str | None = Field(default=None, description="다음 후속 질문에 사용할 최소 상태 토큰")
    question_category: str | None = Field(default=None, description="메타데이터 chat_question_category_details에서 해석할 질문 유형 코드")


class ChatStreamStage(StrEnum):
    """답변 준비 상태에 표시할 서버 작업 단계.

    모델의 내부 추론이 아니라 사용자가 확인 가능한 처리 상태만 표현한다.
    """

    UNDERSTANDING_REQUEST = "UNDERSTANDING_REQUEST"
    PREPARING_EVIDENCE = "PREPARING_EVIDENCE"
    COMPOSING_RESPONSE = "COMPOSING_RESPONSE"
    DELIVERING_RESPONSE = "DELIVERING_RESPONSE"

class ChatStreamSegment(BaseModel):
    """분할 답변에서 현재 처리 중인 묶음의 공개 정보."""

    index: int = Field(ge=1, description="1부터 시작하는 현재 묶음 번호")
    total: int = Field(ge=1, description="이번 응답에서 전달할 전체 묶음 수")


class ChatStreamContinuation(BaseModel):
    """현재 스트림 이후 남은 분할 답변의 재개 위치."""

    next_segment_offset: int = Field(ge=0, description="다음 스트림이 시작할 세그먼트 오프셋")
    remaining_segments: int = Field(ge=0, description="아직 전달하지 않은 세그먼트 수")


class ChatStreamError(BaseModel):
    """SSE 연결이 시작된 뒤 전달하는 안전한 오류 정보."""

    code: str = Field(description="안전한 스트림 오류 코드")
    message: str = Field(description="사용자에게 표시할 오류 안내")
    retryable: bool = Field(default=False, description="같은 요청을 재시도할 수 있는지 여부")
    next_action: str | None = Field(default=None, description="권장 후속 행동 코드")


class ChatStreamEventBase(BaseModel):
    """모든 chat SSE data payload가 공유하는 식별자와 순번."""

    stream_id: str = Field(description="현재 SSE 응답을 식별하는 서버 발급 ID")
    sequence: int = Field(ge=0, description="SSE id와 같은 단조 증가 sequence")


class ChatStreamProgressEvent(ChatStreamEventBase):
    """답변 준비 상태 변화 이벤트."""

    event: Literal["progress"] = Field(default="progress", description="SSE 이벤트 유형")
    stage: ChatStreamStage = Field(description="메타데이터 chat_progress_stage_details에서 해석할 진행 단계 코드")
    message: str = Field(max_length=300, description="사용자에게 표시할 현재 준비 단계 안내")
    question_category: str | None = Field(default=None, description="메타데이터 chat_question_category_details에서 해석할 질문 유형 코드")
    context_used: bool = Field(default=False, description="검증된 직전 대화 상태를 사용했는지 여부")
    segment: ChatStreamSegment | None = Field(default=None, description="현재 작성 중인 분할 답변 묶음")


class ChatStreamDeltaEvent(ChatStreamEventBase):
    """화면에 이어 붙일 답변 본문 조각."""

    event: Literal["delta"] = Field(default="delta", description="SSE 이벤트 유형")
    text: str = Field(min_length=1, description="화면에 이어 붙일 답변 본문 조각")
    segment: ChatStreamSegment | None = Field(default=None, description="본문 조각이 속한 답변 묶음")


class ChatStreamSegmentCompleteEvent(ChatStreamEventBase):
    """한 답변 묶음의 출처 확정 이벤트."""

    event: Literal["segment_complete"] = Field(default="segment_complete", description="SSE 이벤트 유형")
    segment: ChatStreamSegment = Field(description="완료된 답변 묶음")
    sources: list[ChatSource] = Field(default_factory=list, description="완료된 묶음에서 사용한 출처")


class ChatStreamCompletedEvent(ChatStreamEventBase):
    """완성된 ChatResponse를 전달하고 스트림을 종료하는 이벤트."""

    event: Literal["completed"] = Field(default="completed", description="SSE 이벤트 유형")
    response: ChatResponse = Field(description="스트림으로 완성한 최종 채팅 응답")
    continuation: ChatStreamContinuation | None = Field(default=None, description="이어보기 가능한 남은 답변 정보")


class ChatStreamFailedEvent(ChatStreamEventBase):
    """부분 응답 보존 여부를 포함해 스트림을 종료하는 실패 이벤트."""

    event: Literal["failed"] = Field(default="failed", description="SSE 이벤트 유형")
    error: ChatStreamError = Field(description="스트림 연결 후 발생한 안전한 오류")
    partial_answer_available: bool = Field(default=False, description="이미 표시된 부분 답변이 있는지 여부")
    continuation: ChatStreamContinuation | None = Field(default=None, description="오류 뒤 이어보기 가능한 답변 정보")
    conversation_token: str | None = Field(default=None, description="남은 답변 묶음을 재개할 다음 요청용 대화 상태 토큰")
