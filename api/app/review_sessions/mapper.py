"""검토 세션 도메인 엔티티와 ORM Row를 명시적으로 변환한다."""

from copy import deepcopy
from datetime import UTC, datetime

from app.db.models import ReviewSessionRow
from app.review_sessions.domain import (
    ReviewSession,
    ReviewSessionState,
    ScopeStatus,
    SelectionSource,
)


def _as_utc(value: datetime) -> datetime:
    """SQLite가 timezone을 제거한 datetime을 UTC aware 값으로 복구한다."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return _as_utc(value) if value is not None else None


def review_session_to_row(entity: ReviewSession) -> ReviewSessionRow:
    """검토 세션 엔티티의 현재 스냅샷을 새 ORM Row로 변환한다."""
    return ReviewSessionRow(
        id=entity.id,
        access_token_hash=entity.access_token_hash,
        state=entity.state.value,
        scope_status=entity.scope_status.value if entity.scope_status else None,
        scope_result=deepcopy(entity.scope_result),
        suggested_contract_type=entity.suggested_contract_type,
        selected_contract_type=entity.selected_contract_type,
        selection_source=(
            entity.selection_source.value if entity.selection_source else None
        ),
        out_of_scope_confirmed_at=entity.out_of_scope_confirmed_at,
        original_file_name=entity.original_file_name,
        file_size_bytes=entity.file_size_bytes,
        storage_path=entity.storage_path,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        expires_at=entity.expires_at,
    )


def update_review_session_row(
    row: ReviewSessionRow,
    entity: ReviewSession,
) -> None:
    """기존 ORM Row를 엔티티의 현재 스냅샷으로 갱신한다."""
    row.access_token_hash = entity.access_token_hash
    row.state = entity.state.value
    row.scope_status = entity.scope_status.value if entity.scope_status else None
    row.scope_result = deepcopy(entity.scope_result)
    row.suggested_contract_type = entity.suggested_contract_type
    row.selected_contract_type = entity.selected_contract_type
    row.selection_source = (
        entity.selection_source.value if entity.selection_source else None
    )
    row.out_of_scope_confirmed_at = entity.out_of_scope_confirmed_at
    row.original_file_name = entity.original_file_name
    row.file_size_bytes = entity.file_size_bytes
    row.storage_path = entity.storage_path
    row.created_at = entity.created_at
    row.updated_at = entity.updated_at
    row.expires_at = entity.expires_at


def review_session_from_row(row: ReviewSessionRow) -> ReviewSession:
    """ORM Row를 외부 프레임워크에 의존하지 않는 엔티티로 변환한다."""
    return ReviewSession(
        id=row.id,
        access_token_hash=row.access_token_hash,
        state=ReviewSessionState(row.state),
        scope_status=ScopeStatus(row.scope_status) if row.scope_status else None,
        scope_result=deepcopy(row.scope_result),
        suggested_contract_type=row.suggested_contract_type,
        selected_contract_type=row.selected_contract_type,
        selection_source=(
            SelectionSource(row.selection_source) if row.selection_source else None
        ),
        out_of_scope_confirmed_at=_optional_utc(row.out_of_scope_confirmed_at),
        original_file_name=row.original_file_name,
        file_size_bytes=row.file_size_bytes,
        storage_path=row.storage_path,
        created_at=_as_utc(row.created_at),
        updated_at=_as_utc(row.updated_at),
        expires_at=_as_utc(row.expires_at),
    )
