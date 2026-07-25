"""Chat API와 LLM 구조화 출력 DTO."""

from typing import Literal

from pydantic import BaseModel, Field


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    focus_clause_id: str | None = Field(default=None, max_length=128)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=10)


class ChatSource(BaseModel):
    type: Literal["USER_CLAUSE", "STANDARD_CLAUSE", "LAW"]
    id: str | None = None
    law_name: str | None = None
    article: str | None = None


class ChatStructuredOutput(BaseModel):
    outcome: Literal["ANSWERED", "REFUSED", "INSUFFICIENT_GROUNDING"]
    answer: str | None = None
    sources: list[ChatSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    outcome: Literal[
        "ANSWERED",
        "REFUSED",
        "INSUFFICIENT_GROUNDING",
        "LLM_OUTPUT_INVALID",
    ]
    answer: str | None = None
    refused: bool
    sources: list[ChatSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    tool_status: str
    disclaimer: str
