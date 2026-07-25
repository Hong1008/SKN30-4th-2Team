"""검토 세션 API의 요청·응답 DTO."""

from datetime import datetime

from pydantic import BaseModel, Field


class UploadInfo(BaseModel):
    """업로드 파일의 비민감 메타데이터."""

    file_name: str
    size_bytes: int
    extension: str


class ContractTypeCandidate(BaseModel):
    """확률이 아닌 MCP 결정론적 근거 점수를 가진 계약 유형 후보."""

    contract_type: str
    evidence_score: int


class ReviewSessionResponse(BaseModel):
    """세션 생성·상태 복구 응답."""

    session_id: str
    review_state: str
    upload: UploadInfo | None = None
    scope_status: str | None = None
    scope_message: str | None = None
    suggested_contract_type: str | None = None
    candidates: list[ContractTypeCandidate] = Field(default_factory=list)
    matched_clause_count: int = 0
    exclusion_markers: list[str] = Field(default_factory=list)
    selected_contract_type: str | None = None
    selection_source: str | None = None
    out_of_scope_confirmed_at: datetime | None = None
    can_start_review: bool = False
    allowed_actions: list[str] = Field(default_factory=list)
    expires_at: datetime


class ContractTypeSelectionRequest(BaseModel):
    """계약 유형 선택 요청."""

    selected_contract_type: str = Field(min_length=1, max_length=64)
    selection_source: str = Field(default="MANUAL", min_length=1, max_length=32)


class OutOfScopeConfirmationRequest(BaseModel):
    """범위 외 계속 진행 확인 요청."""

    confirmed: bool
