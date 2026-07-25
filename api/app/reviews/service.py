"""검토 접수·조회·재시도 Use Case."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.common.errors import ConflictError, ExpiredError
from app.config import Settings
from app.review_sessions.activity import touch_session
from app.review_sessions.domain import ReviewSession, ReviewSessionState
from app.reviews.domain import Review, ReviewState
from app.reviews.repository import SqlAlchemyReviewRepository


def _ensure_startable(session: ReviewSession) -> None:
    """세션이 검토를 시작할 수 있는 상태인지 확인한다."""
    if session.state is ReviewSessionState.EXPIRED or session.is_expired(
        datetime.now(UTC)
    ):
        raise ExpiredError(
            code="SESSION_EXPIRED",
            message="검토 세션이 만료되었습니다.",
            next_action="START_NEW_REVIEW",
        )
    if not session.selected_contract_type:
        raise ConflictError(
            code="CONTRACT_TYPE_SELECTION_REQUIRED",
            message="계약 유형을 먼저 선택해 주세요.",
            next_action="SELECT_CONTRACT_TYPE",
        )
    if (
        session.scope_status is not None
        and session.scope_status.value == "EMPTY_DOCUMENT"
    ):
        raise ConflictError(
            code="CONTRACT_TYPE_SELECTION_REQUIRED",
            message="검토 가능한 문서를 다시 업로드해 주세요.",
            next_action="REUPLOAD",
        )
    if (
        session.scope_status is not None
        and session.scope_status.value == "OUT_OF_SCOPE"
        and session.out_of_scope_confirmed_at is None
    ):
        raise ConflictError(
            code="OUT_OF_SCOPE_CONFIRMATION_REQUIRED",
            message="범위 외 문서 계속 진행을 확인해 주세요.",
            next_action="CONFIRM_OUT_OF_SCOPE",
        )


def create_review(
    db_session: Session,
    session: ReviewSession,
    *,
    idempotency_key: str,
    settings: Settings,
) -> Review:
    """소유 세션에 대해 중복 없는 검토를 접수한다."""
    _ensure_startable(session)
    repository = SqlAlchemyReviewRepository(db_session)
    existing = repository.find_by_idempotency_key(session.id, idempotency_key)
    if existing is not None:
        return existing
    if repository.has_active_for_session(session.id):
        raise ConflictError(
            code="REVIEW_ALREADY_RUNNING",
            message="이미 실행 중인 검토가 있습니다.",
        )
    now = datetime.now(UTC)
    for previous in repository.list_by_session(session.id):
        previous.state = ReviewState.EXPIRED
        previous.progress = None
        previous.result = None
        previous.error = None
        previous.expires_at = now
        repository.save(previous)
    entity = Review(
        id=f"rev_{uuid.uuid4().hex}",
        session_id=session.id,
        idempotency_key=idempotency_key,
        state=ReviewState.QUEUED,
        contract_type=session.selected_contract_type,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        progress={
            "sequence": 0,
            "stage": "PREPARE",
            "current": 0,
            "total": None,
            "percent": 0,
            "message": "검토를 준비하고 있습니다.",
        },
    )
    repository.add(entity)
    touch_session(
        db_session,
        session,
        ttl_seconds=settings.session_ttl_seconds,
        now=now,
    )
    return entity


def retry_review(
    db_session: Session,
    review: Review,
    *,
    idempotency_key: str,
    settings: Settings,
) -> Review:
    """재시도 가능한 실패에서 새 review_id를 발급한다."""
    if review.state is not ReviewState.FAILED or not review.error:
        raise ConflictError(
            code="REVIEW_NOT_COMPLETED",
            message="현재 검토는 재시도할 수 없습니다.",
        )
    if not review.error.get("retryable", False):
        raise ConflictError(
            code="REVIEW_NOT_COMPLETED",
            message="현재 검토는 재시도할 수 없습니다.",
        )
    repository = SqlAlchemyReviewRepository(db_session)
    existing = repository.find_by_idempotency_key(review.session_id, idempotency_key)
    if existing is not None:
        return existing
    now = datetime.now(UTC)
    retried = Review(
        id=f"rev_{uuid.uuid4().hex}",
        session_id=review.session_id,
        idempotency_key=idempotency_key,
        state=ReviewState.QUEUED,
        contract_type=review.contract_type,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        retry_of_review_id=review.id,
        progress={"sequence": 0, "stage": "PREPARE", "percent": 0},
    )
    repository.add(retried)
    return retried
