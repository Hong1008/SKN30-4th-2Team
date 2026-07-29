"""Chat API와 LLM 구조화 출력 DTO."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ChatRole(StrEnum):
    """대화 발화 주체."""

    USER = "user"
    ASSISTANT = "assistant"


class ChatOutcome(StrEnum):
    """질의응답 결과 유형."""

    ANSWERED = "ANSWERED"
    REFUSED = "REFUSED"
    INSUFFICIENT_GROUNDING = "INSUFFICIENT_GROUNDING"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"


class ChatSourceType(StrEnum):
    """참조 근거 유형."""

    USER_CLAUSE = "USER_CLAUSE"
    STANDARD_CLAUSE = "STANDARD_CLAUSE"
    LAW = "LAW"


class ChatHistoryMessage(BaseModel):
    role: ChatRole = Field(description="발화 주체 (user 또는 assistant)")
    content: str = Field(
        min_length=1, max_length=2000, description="대화 메시지 내용"
    )


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1, max_length=2000, description="사용자 질문 메시지"
    )
    focus_clause_id: str | None = Field(
        default=None, max_length=128, description="질문의 대상이 되는 사용자 조항 식별자"
    )
    history: list[ChatHistoryMessage] = Field(
        default_factory=list, max_length=10, description="이전 대화 히스토리 (최대 10개)"
    )


class ChatSource(BaseModel):
    type: ChatSourceType = Field(
        description="참조 근거 유형 (USER_CLAUSE, STANDARD_CLAUSE, LAW)"
    )
    id: str | None = Field(default=None, description="참조 조항 또는 근거 식별자")
    display_label: str | None = Field(
        default=None,
        description="내부 식별자를 노출하지 않는 사용자용 출처 명칭",
    )
    law_name: str | None = Field(default=None, description="법령 명칭")
    article: str | None = Field(default=None, description="법령 조항 번호")
    source_url: str | None = Field(
        default=None,
        description="검증된 법령 원문 출처 URL",
    )


class ChatStructuredOutput(BaseModel):
    outcome: ChatOutcome = Field(description="LLM 응답 결과 유형")
    answer: str | None = Field(default=None, description="LLM 답변 본문")
    sources: list[ChatSource] = Field(
        default_factory=list, description="답변 시 참조한 출처 목록"
    )
    limitations: list[str] = Field(
        default_factory=list, description="답변의 제약 사항/한계 설명"
    )


class ChatResponse(BaseModel):
    outcome: ChatOutcome = Field(
        description="질의응답 결과 유형 (ANSWERED, REFUSED, INSUFFICIENT_GROUNDING, LLM_OUTPUT_INVALID)"
    )
    answer: str | None = Field(default=None, description="질의응답 답변 내용")
    refused: bool = Field(description="질문 거부/범위 외 여부")
    sources: list[ChatSource] = Field(
        default_factory=list, description="참조 근거 출처 목록"
    )
    limitations: list[str] = Field(
        default_factory=list, description="답변 관련 한계 사항"
    )
    tool_status: str = Field(description="도구/MCP 연동 상태")
    disclaimer: str = Field(description="법률 자문 불가 면책 조항 문구")
