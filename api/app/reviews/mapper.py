"""검토 도메인 엔티티와 ORM Row를 명시적으로 변환한다."""

from copy import deepcopy
from datetime import UTC, datetime

from app.db.models import ReviewRow
from app.reviews.domain import MCPReviewStatus, Review, ReviewState


def _as_utc(value: datetime) -> datetime:
    """SQLite가 timezone을 제거한 datetime을 UTC aware 값으로 복구한다."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return _as_utc(value) if value is not None else None


def review_to_row(entity: Review) -> ReviewRow:
    """검토 엔티티의 현재 스냅샷을 새 ORM Row로 변환한다."""
    return ReviewRow(
        id=entity.id,
        session_id=entity.session_id,
        retry_of_review_id=entity.retry_of_review_id,
        idempotency_key=entity.idempotency_key,
        state=entity.state.value,
        mcp_review_status=(
            entity.mcp_review_status.value if entity.mcp_review_status else None
        ),
        contract_type=entity.contract_type,
        progress=deepcopy(entity.progress),
        result=deepcopy(entity.result),
        error=deepcopy(entity.error),
        created_at=entity.created_at,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
        expires_at=entity.expires_at,
    )


def update_review_row(row: ReviewRow, entity: Review) -> None:
    """기존 ORM Row를 엔티티의 현재 스냅샷으로 갱신한다."""
    row.session_id = entity.session_id
    row.retry_of_review_id = entity.retry_of_review_id
    row.idempotency_key = entity.idempotency_key
    row.state = entity.state.value
    row.mcp_review_status = (
        entity.mcp_review_status.value if entity.mcp_review_status else None
    )
    row.contract_type = entity.contract_type
    row.progress = deepcopy(entity.progress)
    row.result = deepcopy(entity.result)
    row.error = deepcopy(entity.error)
    row.created_at = entity.created_at
    row.started_at = entity.started_at
    row.completed_at = entity.completed_at
    row.expires_at = entity.expires_at


def review_from_row(row: ReviewRow) -> Review:
    """ORM Row를 외부 프레임워크에 의존하지 않는 엔티티로 변환한다."""
    return Review(
        id=row.id,
        session_id=row.session_id,
        retry_of_review_id=row.retry_of_review_id,
        idempotency_key=row.idempotency_key,
        state=ReviewState(row.state),
        mcp_review_status=(
            MCPReviewStatus(row.mcp_review_status)
            if row.mcp_review_status
            else None
        ),
        contract_type=row.contract_type,
        progress=deepcopy(row.progress),
        result=deepcopy(row.result),
        error=deepcopy(row.error),
        created_at=_as_utc(row.created_at),
        started_at=_optional_utc(row.started_at),
        completed_at=_optional_utc(row.completed_at),
        expires_at=_as_utc(row.expires_at),
    )
