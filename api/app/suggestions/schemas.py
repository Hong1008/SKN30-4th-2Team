"""Suggestions API와 LLM 구조화 출력 DTO."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class SuggestionRequest(BaseModel):
    user_clause_id: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=1, max_length=500)
    inputs: dict[str, Any] = Field(default_factory=dict)


class RequiredConfirmation(BaseModel):
    field: str
    placeholder: str


class SuggestionStructuredOutput(BaseModel):
    outcome: Literal["GENERATED", "INSUFFICIENT_GROUNDING"]
    text: str | None = None
    key_changes: list[str] = Field(default_factory=list)
    standard_clause_ids: list[str] = Field(default_factory=list)
    grounding_source_ids: list[str] = Field(default_factory=list)
    required_confirmations: list[RequiredConfirmation] = Field(default_factory=list)


class SuggestionResponse(BaseModel):
    outcome: Literal[
        "GENERATED",
        "INSUFFICIENT_GROUNDING",
        "REQUIRED_VALUE_MISSING",
        "GENERATED_FACT_NOT_GROUNDED",
        "LLM_OUTPUT_INVALID",
    ]
    text: str | None = None
    purpose: str | None = None
    key_changes: list[str] = Field(default_factory=list)
    standard_clause_ids: list[str] = Field(default_factory=list)
    grounding_source_ids: list[str] = Field(default_factory=list)
    required_confirmations: list[RequiredConfirmation] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    disclaimer: str
