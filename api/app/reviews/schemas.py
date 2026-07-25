"""검토 API의 요청·응답 DTO."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MCPReviewResultStatus(StrEnum):
    """WorkShield 전체 검토 공개 응답 상태."""

    OK = "OK"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    CORPUS_UNAVAILABLE = "CORPUS_UNAVAILABLE"
    INVALID_CONFIG = "INVALID_CONFIG"
    PIPELINE_ERROR = "PIPELINE_ERROR"


class ClauseDeviation(StrEnum):
    """사용자 조항의 표준 대비 검토 후보 표식."""

    NONE = "NONE"
    EXTRA = "EXTRA"
    NO_MATCH = "NO_MATCH"


class StandardMatchStatus(StrEnum):
    """표준조항 후보 선택 상태."""

    CANDIDATE_SELECTED = "CANDIDATE_SELECTED"
    NO_CANDIDATE = "NO_CANDIDATE"


class _MCPPublicModel(BaseModel):
    """알 수 없는 필드를 거부하는 WorkShield MCP 공개 DTO 기반 모델."""

    model_config = ConfigDict(extra="forbid")


class MCPStandardClause(_MCPPublicModel):
    """MCP가 반환하는 표준조항 원문과 출처."""

    clause_id: str
    contract_type: str
    category: str
    title: str
    text: str
    source: str
    version: str


class MCPCandidateSelected(_MCPPublicModel):
    """비교할 표준조항 후보가 선택된 match 분기."""

    status: Literal["CANDIDATE_SELECTED"]
    standard: MCPStandardClause
    score: float = Field(ge=0.0, le=1.0)


class MCPNoCandidate(_MCPPublicModel):
    """비교할 표준조항 후보가 없는 match 분기."""

    status: Literal["NO_CANDIDATE"]


MCPStandardMatch = Annotated[
    MCPCandidateSelected | MCPNoCandidate,
    Field(discriminator="status"),
]


class MCPClauseReviewCandidate(_MCPPublicModel):
    """실제 계약서에 존재하는 사용자 조항 검토 후보."""

    user_clause: str = Field(min_length=1)
    deviation: ClauseDeviation
    match: MCPStandardMatch
    toxic_patterns: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_deviation_and_match(self) -> "MCPClauseReviewCandidate":
        """deviation과 match 유니온 사이의 공개 계약을 강제한다."""
        if (
            self.deviation is ClauseDeviation.NONE
            and self.match.status != StandardMatchStatus.CANDIDATE_SELECTED
        ):
            raise ValueError("NONE은 선택된 표준조항 후보가 필요합니다.")
        if (
            self.deviation is ClauseDeviation.NO_MATCH
            and self.match.status != StandardMatchStatus.NO_CANDIDATE
        ):
            raise ValueError("NO_MATCH에는 표준조항 후보가 없어야 합니다.")
        return self


class MCPMissingStandardCandidate(_MCPPublicModel):
    """계약서 전체에서 대응 조항을 찾지 못한 표준조항 후보."""

    standard: MCPStandardClause


class MCPReviewResult(_MCPPublicModel):
    """`review_contract_candidates`의 전체 공개 응답 계약."""

    status: MCPReviewResultStatus
    contract_type: str
    clause_results: list[MCPClauseReviewCandidate] = Field(default_factory=list)
    missing_standard_clauses: list[MCPMissingStandardCandidate] = Field(
        default_factory=list
    )
    message: str | None = None

    @field_validator(
        "clause_results",
        "missing_standard_clauses",
        mode="before",
    )
    @classmethod
    def normalize_nullable_result_arrays(cls, value: object) -> object:
        """MCP의 누락 또는 명시적 null 결과 배열을 같은 빈 배열로 처리한다."""
        return [] if value is None else value

    @model_validator(mode="after")
    def validate_failed_response_is_empty(self) -> "MCPReviewResult":
        """실패 상태가 부분 결과를 성공처럼 노출하지 못하게 한다."""
        if self.status is not MCPReviewResultStatus.OK and (
            self.clause_results or self.missing_standard_clauses
        ):
            raise ValueError("OK가 아닌 응답에는 검토 결과를 포함할 수 없습니다.")
        return self


class ReviewClauseResult(MCPClauseReviewCandidate):
    """백엔드가 결정적 사용자 조항 ID를 부여한 공개 결과."""

    user_clause_id: str = Field(min_length=1)


class NormalizedReviewResult(_MCPPublicModel):
    """검증된 MCP 결과에 API 소유 식별자를 결합한 저장 스냅샷."""

    status: MCPReviewResultStatus
    contract_type: str
    clause_results: list[ReviewClauseResult]
    missing_standard_clauses: list[MCPMissingStandardCandidate]
    message: str | None = None


class CodeLabel(BaseModel):
    """프론트가 하드코딩 없이 표시할 수 있는 코드와 표시명."""

    code: str
    label: str


class ReviewResultStandardClause(BaseModel):
    """결과 화면에 노출하는 표준조항과 출처."""

    clause_id: str
    contract_type: str
    category: CodeLabel
    title: str
    text: str
    source: str
    version: str


class ReviewResultMatch(BaseModel):
    """표준조항 후보 선택 여부."""

    status: StandardMatchStatus
    standard: ReviewResultStandardClause | None = None


class ReviewClauseResultResponse(BaseModel):
    """사용자 계약서에 실제로 존재하는 조항의 표시용 결과."""

    user_clause_id: str
    user_clause: str
    deviation: CodeLabel
    match: ReviewResultMatch
    explanation: str
    toxic_patterns: list[CodeLabel]


class MissingStandardClauseResponse(BaseModel):
    """계약서 전체에서 대응 내용을 찾지 못한 표준조항 후보."""

    result_type: CodeLabel
    standard: ReviewResultStandardClause
    explanation: str


class ReviewResultMetadata(BaseModel):
    """완료된 검토 결과의 상태와 수명주기 메타데이터."""

    review_id: str
    review_state: str
    mcp_review_status: str
    contract_type: str
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime
    disclaimer: str


class ReviewClauseResultCounts(BaseModel):
    """사용자 조항 결과 코드별 개수."""

    total: int = Field(ge=0)
    NONE: int = Field(ge=0)
    EXTRA: int = Field(ge=0)
    NO_MATCH: int = Field(ge=0)


class ReviewResultsSummary(BaseModel):
    """결과 화면 상단 요약."""

    clause_results: ReviewClauseResultCounts
    missing_standard_clauses: int = Field(ge=0)
    toxic_pattern_candidates: int = Field(ge=0)


class ReviewResultsResponse(BaseModel):
    """문서화된 검토 결과 조회 응답."""

    review: ReviewResultMetadata
    summary: ReviewResultsSummary
    clause_results: list[ReviewClauseResultResponse]
    missing_standard_clauses: list[MissingStandardClauseResponse]


class ReviewCreateRequest(BaseModel):
    """검토 시작 요청."""

    session_id: str = Field(min_length=1, max_length=64)


class ReviewResponse(BaseModel):
    """검토 상태 조회 응답."""

    review_id: str
    session_id: str
    review_state: str
    mcp_review_status: str | None = None
    progress: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime


class ReviewCreateResponse(BaseModel):
    """비동기 검토 접수 응답."""

    review_id: str
    review_state: str
    session_id: str
    retry_of: str | None = None


class ReviewCancelResponse(BaseModel):
    """검토 결과 폐기와 파일 정리 응답."""

    review_id: str
    review_state: str
    deleted: bool
