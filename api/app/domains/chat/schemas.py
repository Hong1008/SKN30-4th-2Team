"""Chat API 공개 DTO."""

from enum import StrEnum

from pydantic import BaseModel, Field


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


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    focus_clause_id: str | None = Field(default=None, max_length=128)
    history: list[dict[str, str]] = Field(
        default_factory=list,
        max_length=2,
    )


class ChatSource(BaseModel):
    type: ChatSourceType
    id: str | None = None
    display_label: str | None = None
    standard_contract_label: str | None = None
    law_name: str | None = None
    article: str | None = None
    source_url: str | None = None


class ChatResponse(BaseModel):
    outcome: ChatOutcome
    answer: str | None = None
    refused: bool
    sources: list[ChatSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    tool_status: str
    disclaimer: str
