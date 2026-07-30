"""Suggestions API와 LLM 구조화 출력 DTO."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, RootModel


class SuggestionOutcome(StrEnum):
    """제안 생성 결과 유형."""

    GENERATED = "GENERATED"
    INSUFFICIENT_GROUNDING = "INSUFFICIENT_GROUNDING"
    REQUIRED_VALUE_MISSING = "REQUIRED_VALUE_MISSING"
    GENERATED_FACT_NOT_GROUNDED = "GENERATED_FACT_NOT_GROUNDED"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"


class SuggestionEvidenceLevel(StrEnum):
    """표준조항 근거의 확정 수준."""

    CONFIRMED_STANDARD = "CONFIRMED_STANDARD"
    CANDIDATE_STANDARD = "CANDIDATE_STANDARD"


class SuggestionReasonCode(StrEnum):
    """협의 문구를 생성하지 못한 비민감 사유."""

    USER_CLAUSE_MISSING = "USER_CLAUSE_MISSING"
    STANDARD_CANDIDATE_MISSING = "STANDARD_CANDIDATE_MISSING"
    STANDARD_CLAUSE_ID_MISSING = "STANDARD_CLAUSE_ID_MISSING"
    CLAUSE_CATEGORY_MISSING = "CLAUSE_CATEGORY_MISSING"
    REQUIRED_VALUE_MISSING = "REQUIRED_VALUE_MISSING"


class SuggestionSourceKey(StrEnum):
    """LLM이 선택하는 검증된 입력 근거의 논리 키."""

    USER = "SRC_USER"
    STANDARD = "SRC_STANDARD"
    GROUNDING = "SRC_GROUNDING"


class SuggestionSourceType(StrEnum):
    """협의문구 응답에 표시하는 검증된 근거 유형."""

    USER_CLAUSE = "USER_CLAUSE"
    STANDARD_CLAUSE = "STANDARD_CLAUSE"
    LAW = "LAW"


class SuggestionSource(BaseModel):
    """내부 ID와 사용자 표시 정보를 함께 보존하는 협의문구 출처."""

    type: SuggestionSourceType = Field(description="출처 유형")
    id: str = Field(description="검증에 사용하는 내부 출처 식별자")
    display_label: str | None = Field(default=None, description="사용자용 출처 명칭")
    standard_contract_label: str | None = Field(
        default=None,
        description="표준조항 출처의 사용자용 표준계약서 명칭",
    )
    law_name: str | None = Field(default=None, description="법령 명칭")
    article: str | None = Field(default=None, description="법령 조항 번호")
    source_url: str | None = Field(default=None, description="검증된 법령 원문 URL")


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


class SuggestionGeneratedOutput(BaseModel):
    """LLM이 생성하는 협의 문구와 논리 근거 선택 결과."""

    outcome: Literal[SuggestionOutcome.GENERATED] = Field(
        description="생성 성공 결과 유형"
    )
    suggestion: str = Field(min_length=1, description="생성된 협의 문구 초안")
    major_changes: list[str] = Field(
        default_factory=list, description="주요 변경 사항 목록"
    )
    used_source_keys: list[SuggestionSourceKey] = Field(
        min_length=1,
        description=(
            "협의 문구에 사용한 검증된 입력 근거 키. "
            "SRC_USER, SRC_STANDARD, SRC_GROUNDING만 선택할 수 있다."
        ),
    )
    required_confirmations: list[RequiredConfirmation] = Field(
        default_factory=list, description="사용자 직접 확인/입력 필요 항목 목록"
    )


class SuggestionInsufficientGroundingOutput(BaseModel):
    """근거가 부족해 협의 문구를 만들 수 없을 때의 LLM 출력."""

    outcome: Literal[SuggestionOutcome.INSUFFICIENT_GROUNDING] = Field(
        description="생성 불가 결과 유형"
    )
    suggestion: None = Field(default=None, description="생성 불가 시 문구 없음")
    major_changes: list[str] = Field(
        default_factory=list, description="주요 변경 사항 목록"
    )
    used_source_keys: list[SuggestionSourceKey] = Field(
        default_factory=list, description="생성 불가 시 사용 근거 키 없음"
    )
    required_confirmations: list[RequiredConfirmation] = Field(
        default_factory=list, description="사용자 직접 확인/입력 필요 항목 목록"
    )


SuggestionStructuredValue = Annotated[
    SuggestionGeneratedOutput | SuggestionInsufficientGroundingOutput,
    Field(discriminator="outcome"),
]


class SuggestionStructuredOutput(RootModel[SuggestionStructuredValue]):
    """생성 성공과 근거 부족을 구분하는 provider 공통 구조화 출력 계약."""


class SuggestionResponse(BaseModel):
    outcome: SuggestionOutcome = Field(
        description="제안 생성 결과 유형 (GENERATED, INSUFFICIENT_GROUNDING, REQUIRED_VALUE_MISSING, GENERATED_FACT_NOT_GROUNDED, LLM_OUTPUT_INVALID)"
    )
    text: str | None = Field(default=None, description="제안 문구 내용")
    evidence_level: SuggestionEvidenceLevel | None = Field(
        default=None,
        description="협의 문구가 참고한 표준조항 근거의 확정 수준",
    )
    message: str | None = Field(default=None, description="사용자용 결과 안내 문구")
    reason_code: SuggestionReasonCode | None = Field(
        default=None,
        description="생성 불가 원인을 구분하는 비민감 사유 코드",
    )
    purpose: str | None = Field(default=None, description="요청된 수정 목적")
    key_changes: list[str] = Field(
        default_factory=list, description="주요 변경 요점 목록"
    )
    used_source_keys: list[SuggestionSourceKey] = Field(
        default_factory=list, description="LLM이 선택한 검증된 입력 근거 키"
    )
    user_clause_ids: list[str] = Field(
        default_factory=list,
        description="SRC_USER에 대응해 백엔드가 결합한 사용자 조항 ID 목록",
    )
    standard_clause_ids: list[str] = Field(
        default_factory=list,
        description="SRC_STANDARD에 대응해 백엔드가 결합한 표준조항 ID 목록",
    )
    grounding_source_ids: list[str] = Field(
        default_factory=list,
        description="SRC_GROUNDING에 대응해 백엔드가 결합한 법령 근거 ID 목록",
    )
    sources: list[SuggestionSource] = Field(
        default_factory=list,
        description="백엔드가 검증된 ID에서 조립한 사용자 표시용 출처 목록",
    )
    required_confirmations: list[RequiredConfirmation] = Field(
        default_factory=list, description="사용자 확인 필요 항목 목록"
    )
    missing_inputs: list[str] = Field(
        default_factory=list, description="누락된 필수 입력값 목록"
    )
    disclaimer: str = Field(description="법률 자문 불가 면책 조항 문구")
