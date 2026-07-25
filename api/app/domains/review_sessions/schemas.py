"""검토 세션 API의 요청·응답 DTO."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domains.review_sessions.domain import (
    ReviewSessionState,
    ScopeStatus,
    SelectionSource,
)


class UploadInfo(BaseModel):
    """업로드 파일의 비민감 메타데이터."""

    file_name: str = Field(description="업로드된 파일명")
    size_bytes: int = Field(description="파일 크기 (바이트)")
    extension: str = Field(description="파일 확장자")


class ContractTypeCandidate(BaseModel):
    """확률이 아닌 MCP 결정론적 근거 점수를 가진 계약 유형 후보."""

    contract_type: str = Field(description="추천 계약 유형 코드")
    evidence_score: int = Field(description="MCP 결정론적 근거 점수")


class ReviewSessionResponse(BaseModel):
    """세션 생성·상태 복구 응답."""

    session_id: str = Field(description="검토 세션 고유 식별자")
    review_state: ReviewSessionState = Field(description="현재 검토 세션 상태")
    upload: UploadInfo | None = Field(default=None, description="업로드 파일 메타데이터")
    scope_status: ScopeStatus | None = Field(default=None, description="계약 범위 판별 상태")
    scope_message: str | None = Field(default=None, description="범위 판별 안내 메시지")
    suggested_contract_type: str | None = Field(default=None, description="자동 추천된 계약 유형 코드")
    candidates: list[ContractTypeCandidate] = Field(
        default_factory=list, description="계약 유형 추천 후보 목록"
    )
    matched_clause_count: int = Field(default=0, description="매칭된 조항 수")
    exclusion_markers: list[str] = Field(
        default_factory=list, description="범위 제외 판단 표식 목록"
    )
    selected_contract_type: str | None = Field(
        default=None, description="사용자 또는 추천으로 확정된 계약 유형"
    )
    selection_source: SelectionSource | None = Field(
        default=None, description="계약 유형 선택 경로 (SUGGESTED, CANDIDATE, MANUAL)"
    )
    out_of_scope_confirmed_at: datetime | None = Field(
        default=None, description="범위 외 진행 확인 일시"
    )
    can_start_review: bool = Field(default=False, description="검토 시작 가능 여부")
    allowed_actions: list[str] = Field(
        default_factory=list, description="현재 상태에서 허용된 사용자 행동 목록"
    )
    expires_at: datetime = Field(description="세션 만료 일시")


class ContractTypeSelectionRequest(BaseModel):
    """계약 유형 선택 요청."""

    selected_contract_type: str = Field(
        min_length=1, max_length=64, description="선택한 계약 유형 코드 (예: SW_FREELANCE)"
    )
    selection_source: SelectionSource = Field(
        default=SelectionSource.MANUAL,
        description="선택 경로 (SUGGESTED, CANDIDATE, MANUAL)",
    )


class OutOfScopeConfirmationRequest(BaseModel):
    """범위 외 계속 진행 확인 요청."""

    confirmed: bool = Field(description="범위 외 계약서에 대해 계속 진행 동의 여부")
