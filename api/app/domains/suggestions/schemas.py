"""Suggestions API와 LLM 구조화 출력 DTO."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SuggestionOutcome(StrEnum):
    """제안 생성 결과 유형."""

    GENERATED = "GENERATED"
    INSUFFICIENT_GROUNDING = "INSUFFICIENT_GROUNDING"
    REQUIRED_VALUE_MISSING = "REQUIRED_VALUE_MISSING"
    GENERATED_FACT_NOT_GROUNDED = "GENERATED_FACT_NOT_GROUNDED"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"


class SuggestionRequest(BaseModel):
    user_clause_id: str = Field(
        min_length=1,
        max_length=128,
        description="협의 문구를 생성할 대상 사용자 조항 ID",
    )
    purpose: str = Field(
        min_length=1,
        max_length=500,
        description="수정/협의 목적 및 희망 방향",
    )
    inputs: dict[str, Any] = Field(
        default_factory=dict, description="추가 입력 변수 값"
    )


class RequiredConfirmation(BaseModel):
    field: str = Field(description="확인 필요 필드/변수명")
    placeholder: str = Field(description="입력 힌트/치환문구")


class SuggestionStructuredOutput(BaseModel):
    outcome: SuggestionOutcome = Field(description="LLM 생성 결과 유형")
    text: str | None = Field(default=None, description="생성된 협의 문구 초안")
    key_changes: list[str] = Field(
        default_factory=list, description="주요 변경 사항 목록"
    )
    standard_clause_ids: list[str] = Field(
        default_factory=list, description="참조한 표준조항 ID 목록"
    )
    grounding_source_ids: list[str] = Field(
        default_factory=list, description="참조한 법령 근거 ID 목록"
    )
    required_confirmations: list[RequiredConfirmation] = Field(
        default_factory=list, description="사용자 직접 확인/입력 필요 항목 목록"
    )


class SuggestionResponse(BaseModel):
    outcome: SuggestionOutcome = Field(
        description="제안 생성 결과 유형 (GENERATED, INSUFFICIENT_GROUNDING, REQUIRED_VALUE_MISSING, GENERATED_FACT_NOT_GROUNDED, LLM_OUTPUT_INVALID)"
    )
    text: str | None = Field(default=None, description="제안 문구 내용")
    purpose: str | None = Field(default=None, description="요청된 수정 목적")
    key_changes: list[str] = Field(
        default_factory=list, description="주요 변경 요점 목록"
    )
    standard_clause_ids: list[str] = Field(
        default_factory=list, description="참조 표준조항 ID 목록"
    )
    grounding_source_ids: list[str] = Field(
        default_factory=list, description="참조 법령 근거 ID 목록"
    )
    required_confirmations: list[RequiredConfirmation] = Field(
        default_factory=list, description="사용자 확인 필요 항목 목록"
    )
    missing_inputs: list[str] = Field(
        default_factory=list, description="누락된 필수 입력값 목록"
    )
    disclaimer: str = Field(description="법률 자문 불가 면책 조항 문구")
