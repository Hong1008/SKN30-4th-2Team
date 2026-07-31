"""검토 API의 요청·응답 DTO."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.reviews.domain import ProgressStage, ReviewState


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

    clause_id: str = Field(description="표준조항 식별자")
    contract_type: str = Field(description="계약 유형 코드")
    category: str = Field(description="카테고리 코드")
    title: str = Field(description="표준조항 제목")
    text: str = Field(description="표준조항 본문")
    source: str = Field(description="표준조항 출처")
    version: str = Field(description="표준조항 버전")


class MCPCandidateSelected(_MCPPublicModel):
    """비교할 표준조항 후보가 선택된 match 분기."""

    status: Literal["CANDIDATE_SELECTED"] = Field(description="표준조항 후보 선택 상태")
    standard: MCPStandardClause = Field(description="매칭된 표준조항 상세 정보")
    score: float = Field(ge=0.0, le=1.0, description="매칭 유사도 점수 (0.0~1.0)")


class MCPNoCandidate(_MCPPublicModel):
    """비교할 표준조항 후보가 없는 match 분기."""

    status: Literal["NO_CANDIDATE"] = Field(description="표준조항 후보 없음 상태")


MCPStandardMatch = Annotated[
    MCPCandidateSelected | MCPNoCandidate,
    Field(discriminator="status"),
]


class MCPClauseReviewCandidate(_MCPPublicModel):
    """실제 계약서에 존재하는 사용자 조항 검토 후보."""

    user_clause: str = Field(min_length=1, description="사용자 계약서 조항 원문")
    deviation: ClauseDeviation = Field(
        description="표준 대비 변형/차이 코드 (NONE, EXTRA, NO_MATCH)"
    )
    match: MCPStandardMatch = Field(description="표준조항 매칭 정보")
    toxic_patterns: list[str] = Field(
        default_factory=list, description="탐지된 독소/주의 패턴 코드 목록"
    )

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

    standard: MCPStandardClause = Field(description="누락된 표준조항 정보")


class MCPReviewResult(_MCPPublicModel):
    """`review_contract_candidates`의 전체 공개 응답 계약."""

    status: MCPReviewResultStatus = Field(
        description="MCP 검토 상태 (OK, EMPTY_DOCUMENT 등)"
    )
    contract_type: str = Field(description="검토 대상 계약 유형")
    clause_results: list[MCPClauseReviewCandidate] = Field(
        default_factory=list, description="사용자 조항 검토 결과 목록"
    )
    missing_standard_clauses: list[MCPMissingStandardCandidate] = Field(
        default_factory=list, description="누락된 표준조항 체크리스트 목록"
    )
    message: str | None = Field(default=None, description="결과 관련 안내 메시지")

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

    user_clause_id: str = Field(
        min_length=1, description="사용자 조항 식별자 (예: uc_rev_01J_1)"
    )


class NormalizedReviewResult(_MCPPublicModel):
    """검증된 MCP 결과에 API 소유 식별자를 결합한 저장 스냅샷."""

    status: MCPReviewResultStatus = Field(description="MCP 검토 상태")
    contract_type: str = Field(description="계약 유형")
    clause_results: list[ReviewClauseResult] = Field(
        description="식별자가 부여된 사용자 조항 검토 결과 목록"
    )
    missing_standard_clauses: list[MCPMissingStandardCandidate] = Field(
        description="누락된 표준조항 체크리스트 목록"
    )
    toxic_pattern_labels: dict[str, str] = Field(
        default_factory=dict,
        description="검토 시점 MCP 주의 패턴 코드와 기존 표시 제목의 스냅샷",
    )
    message: str | None = Field(default=None, description="결과 안내 메시지")


class CodeLabel(BaseModel):
    """프론트가 하드코딩 없이 표시할 수 있는 코드와 표시명."""

    code: str = Field(description="식별 코드")
    label: str = Field(description="화면 표시 라벨")


class ReviewResultStandardClause(BaseModel):
    """내부 출처 메타데이터를 제외한 사용자용 표준조항."""

    standard_contract_label: str = Field(description="사용자용 표준계약서 명칭")
    category: CodeLabel = Field(description="카테고리 코드 및 표시명")
    title: str = Field(description="표준조항 제목")
    text: str = Field(description="표준조항 본문")


class ReviewResultMatch(BaseModel):
    """표준조항 후보 선택 여부."""

    status: StandardMatchStatus = Field(
        description="매칭 상태 (CANDIDATE_SELECTED, NO_CANDIDATE)"
    )
    standard: ReviewResultStandardClause | None = Field(
        default=None, description="선택된 표준조항 상세 정보"
    )


class ReviewClauseResultResponse(BaseModel):
    """사용자 계약서에 실제로 존재하는 조항의 표시용 결과."""

    user_clause_id: str = Field(description="사용자 조항 식별자")
    user_clause: str = Field(description="사용자 조항 원문")
    deviation: CodeLabel = Field(
        description="변형 코드 및 표시명 (NONE, EXTRA, NO_MATCH)"
    )
    match: ReviewResultMatch = Field(description="표준조항 매칭 정보")
    explanation: str = Field(description="조항 검토 설명/안내 문구")
    toxic_patterns: list[CodeLabel] = Field(
        description="탐지된 주의/독소 패턴 코드 및 표시명 목록"
    )


class MissingStandardClauseResponse(BaseModel):
    """계약서 전체에서 대응 내용을 찾지 못한 표준조항 후보."""

    result_type: CodeLabel = Field(description="결과 유형 (MISSING)")
    standard: ReviewResultStandardClause = Field(description="누락된 표준조항 상세")
    explanation: str = Field(description="누락 조항 안내 설명 문구")


class ReviewResultMetadata(BaseModel):
    """완료된 검토 결과의 상태와 수명주기 메타데이터."""

    review_id: str = Field(description="검토 고유 식별자")
    review_state: ReviewState = Field(description="검토 진행 상태 (COMPLETED)")
    mcp_review_status: MCPReviewResultStatus = Field(description="MCP 검토 원본 상태 (OK)")
    contract_type: str = Field(description="확정된 계약 유형 코드")
    started_at: datetime | None = Field(description="검토 시작 일시")
    completed_at: datetime | None = Field(description="검토 완료 일시")
    expires_at: datetime = Field(description="결과 만료 일시")
    disclaimer: str = Field(description="법률 자문 불가 면책 조항 문구")


class ReviewClauseResultCounts(BaseModel):
    """사용자 조항 결과 코드별 개수."""

    total: int = Field(ge=0, description="전체 검토 조항 수")
    NONE: int = Field(ge=0, description="표준 대응 후보 있음 조항 수")
    EXTRA: int = Field(ge=0, description="추가·변형 확인 필요 조항 수")
    NO_MATCH: int = Field(ge=0, description="표준 검색 후보 없음 조항 수")


class ReviewResultsSummary(BaseModel):
    """결과 화면 상단 요약."""

    clause_results: ReviewClauseResultCounts = Field(
        description="사용자 조항 결과 요약 카운트"
    )
    missing_standard_clauses: int = Field(
        ge=0, description="누락 가능성 있는 표준조항 수"
    )
    toxic_pattern_candidates: int = Field(
        ge=0, description="독소/주의 패턴 탐지 수"
    )


class ReviewResultsResponse(BaseModel):
    """문서화된 검토 결과 조회 응답."""

    review: ReviewResultMetadata = Field(description="검토 메타데이터")
    summary: ReviewResultsSummary = Field(description="검토 결과 요약 정보")
    clause_results: list[ReviewClauseResultResponse] = Field(
        description="사용자 조항별 검토 결과 목록"
    )
    missing_standard_clauses: list[MissingStandardClauseResponse] = Field(
        description="누락된 표준조항 체크리스트 목록"
    )


class ReviewProgressSnapshot(BaseModel):
    """상태 조회와 SSE에 공통으로 사용하는 정규화된 진행 스냅샷."""

    sequence: int = Field(ge=0, description="단조 증가하는 진행 이벤트 식별자")
    stage: ProgressStage = Field(description="현재 검토 진행 단계")
    current: float = Field(ge=0, description="현재 진행 단위")
    total: float | None = Field(default=None, ge=0, description="전체 진행 단위")
    percent: int = Field(ge=0, le=100, description="단조 증가하는 진행률(%)")
    message: str | None = Field(
        default=None,
        max_length=300,
        description="화면 표시용 진행 안내 문구",
    )


class ReviewExecutionError(BaseModel):
    """백그라운드 검토 실패 시 상태 조회와 SSE가 제공하는 오류 정보."""

    code: str = Field(description="검토 실패 코드")
    retryable: bool = Field(default=False, description="재시도 가능 여부")
    next_action: str | None = Field(
        default=None,
        description="권장 다음 행동 코드 (예: RETRY_REVIEW)",
    )


class ReviewSseEvent(BaseModel):
    """SSE data 필드에 JSON으로 직렬화되는 검토 상태 이벤트."""

    review_id: str = Field(description="검토 식별자")
    sequence: int = Field(ge=0, description="SSE id와 같은 단조 증가 sequence")
    review_state: ReviewState = Field(description="이벤트 시점의 검토 상태")
    stage: ProgressStage | None = Field(default=None, description="현재 진행 단계")
    current: float | None = Field(default=None, ge=0, description="현재 진행 단위")
    total: float | None = Field(default=None, ge=0, description="전체 진행 단위")
    percent: int | None = Field(default=None, ge=0, le=100, description="진행률(%)")
    message: str | None = Field(default=None, description="화면 표시용 진행 안내 문구")
    mcp_review_status: MCPReviewResultStatus | None = Field(
        default=None,
        description="completed/failed 이벤트의 MCP 원본 상태",
    )
    error: ReviewExecutionError | None = Field(
        default=None,
        description="completed/failed 이벤트의 검토 실패 정보",
    )


class ReviewCreateRequest(BaseModel):
    """검토 시작 요청."""

    session_id: str = Field(
        min_length=1, max_length=64, description="검토를 시작할 세션 식별자"
    )


class ReviewResponse(BaseModel):
    """검토 상태 조회 응답."""

    review_id: str = Field(description="검토 식별자")
    session_id: str = Field(description="연관 세션 식별자")
    review_state: ReviewState = Field(
        description="검토 상태 (QUEUED, REVIEWING, COMPLETED, FAILED 등)"
    )
    mcp_review_status: MCPReviewResultStatus | None = Field(
        default=None, description="MCP 검토 원본 상태"
    )
    progress: ReviewProgressSnapshot | None = Field(
        default=None,
        description="정규화된 최신 진행률 및 단계 정보",
    )
    result: NormalizedReviewResult | None = Field(
        default=None,
        description="완료된 검토의 정규화된 내부 결과 스냅샷",
    )
    error: ReviewExecutionError | None = Field(
        default=None,
        description="검토 실패 시 오류 정보. 재시도 UI는 retryable=true일 때만 표시",
    )
    started_at: datetime | None = Field(default=None, description="검토 시작 일시")
    completed_at: datetime | None = Field(default=None, description="검토 완료 일시")
    expires_at: datetime = Field(description="검토 결과 만료 일시")


class ReviewCreateResponse(BaseModel):
    """비동기 검토 접수 응답."""

    review_id: str = Field(description="생성된 검토 식별자")
    review_state: ReviewState = Field(description="초기 검토 상태 (QUEUED)")
    session_id: str = Field(description="연관 세션 식별자")
    retry_of: str | None = Field(
        default=None, description="재시도 대상 이전 검토 식별자"
    )


class ReviewCancelResponse(BaseModel):
    """검토 결과 폐기와 파일 정리 응답."""

    review_id: str = Field(description="취소/폐기된 검토 식별자")
    review_state: ReviewState = Field(description="변경된 검토 상태 (CANCELLED)")
    deleted: bool = Field(description="저장된 원본 파일 및 스냅샷 폐기 여부")
