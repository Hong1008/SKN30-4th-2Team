"""검토 작업의 순수 도메인 타입과 엔티티."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ReviewState(StrEnum):
    """애플리케이션 검토 작업 상태."""

    QUEUED = "QUEUED"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class MCPReviewStatus(StrEnum):
    """MCP 전체 검토 응답의 원본 상태."""

    OK = "OK"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    CORPUS_UNAVAILABLE = "CORPUS_UNAVAILABLE"
    INVALID_CONFIG = "INVALID_CONFIG"
    PIPELINE_ERROR = "PIPELINE_ERROR"


@dataclass(slots=True)
class Review:
    """한 번의 MCP 전체 검토와 결과 스냅샷을 나타내는 Aggregate Root."""

    id: str
    session_id: str
    idempotency_key: str
    state: ReviewState
    contract_type: str
    created_at: datetime
    expires_at: datetime
    retry_of_review_id: str | None = None
    mcp_review_status: MCPReviewStatus | None = None
    progress: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def is_expired(self, now: datetime) -> bool:
        """주어진 시각을 기준으로 검토 결과 만료 여부를 반환한다."""
        return now >= self.expires_at
