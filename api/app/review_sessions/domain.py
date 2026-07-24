"""검토 세션의 순수 도메인 타입과 엔티티."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ReviewSessionState(StrEnum):
    """계약 유형 확정 전후의 검토 세션 상태."""

    ANALYZING_CONTRACT_TYPE = "ANALYZING_CONTRACT_TYPE"
    TYPE_SELECTION_REQUIRED = "TYPE_SELECTION_REQUIRED"
    OUT_OF_SCOPE_CONFIRMATION_REQUIRED = "OUT_OF_SCOPE_CONFIRMATION_REQUIRED"
    READY_TO_REVIEW = "READY_TO_REVIEW"
    REUPLOAD_REQUIRED = "REUPLOAD_REQUIRED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class ScopeStatus(StrEnum):
    """MCP 계약 범위 판별 원본 상태."""

    IN_SCOPE = "IN_SCOPE"
    CONTRACT_TYPE_UNCERTAIN = "CONTRACT_TYPE_UNCERTAIN"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"


class SelectionSource(StrEnum):
    """사용자가 계약 유형을 고른 경로."""

    SUGGESTED = "SUGGESTED"
    CANDIDATE = "CANDIDATE"
    MANUAL = "MANUAL"


@dataclass(slots=True)
class ReviewSession:
    """계약서 파일과 사용자의 계약 유형 선택을 묶는 Aggregate Root."""

    id: str
    access_token_hash: str
    state: ReviewSessionState
    original_file_name: str
    file_size_bytes: int
    storage_path: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    scope_status: ScopeStatus | None = None
    scope_result: dict[str, Any] | None = None
    suggested_contract_type: str | None = None
    selected_contract_type: str | None = None
    selection_source: SelectionSource | None = None
    out_of_scope_confirmed_at: datetime | None = None

    def is_expired(self, now: datetime) -> bool:
        """주어진 시각을 기준으로 세션 만료 여부를 반환한다."""
        return now >= self.expires_at
