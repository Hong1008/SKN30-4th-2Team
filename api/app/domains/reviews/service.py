"""검토 접수·조회·재시도 Use Case."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.common.errors import ConflictError, ExpiredError
from app.domains.review_sessions.activity import touch_session
from app.domains.review_sessions.domain import ReviewSession, ReviewSessionState
from app.domains.review_sessions.policy import (
    DEFAULT_REVIEW_SESSION_POLICY,
    ReviewSessionPolicy,
)
from app.domains.reviews.domain import Review, ReviewState
from app.domains.reviews.repository import SqlAlchemyReviewRepository


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
    policy: ReviewSessionPolicy = DEFAULT_REVIEW_SESSION_POLICY,
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
        if previous.state is ReviewState.EXPIRED:
            continue
        previous.expire(at=now)
        repository.save(previous)
    entity = Review.queued(
        review_id=f"rev_{uuid.uuid4().hex}",
        session_id=session.id,
        idempotency_key=idempotency_key,
        contract_type=session.selected_contract_type,
        created_at=now,
        expires_at=now + timedelta(seconds=policy.session_ttl_seconds),
    )
    repository.add(entity)
    try:
        db_session.flush()
    except IntegrityError as error:
        db_session.rollback()
        raced = repository.find_by_idempotency_key(
            session.id,
            idempotency_key,
        )
        if raced is not None:
            return raced
        raise ConflictError(
            code="REVIEW_ALREADY_RUNNING",
            message="이미 실행 중인 검토가 있습니다.",
        ) from error
    touch_session(
        db_session,
        session,
        ttl_seconds=policy.session_ttl_seconds,
        now=now,
    )
    return entity


def retry_review(
    db_session: Session,
    review: Review,
    *,
    idempotency_key: str,
    policy: ReviewSessionPolicy = DEFAULT_REVIEW_SESSION_POLICY,
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
    if repository.has_active_for_session(review.session_id):
        raise ConflictError(
            code="REVIEW_ALREADY_RUNNING",
            message="이미 실행 중인 검토가 있습니다.",
        )
    now = datetime.now(UTC)
    retried = Review.queued(
        review_id=f"rev_{uuid.uuid4().hex}",
        session_id=review.session_id,
        idempotency_key=idempotency_key,
        contract_type=review.contract_type,
        created_at=now,
        expires_at=now + timedelta(seconds=policy.session_ttl_seconds),
        retry_of_review_id=review.id,
    )
    repository.add(retried)
    try:
        db_session.flush()
    except IntegrityError as error:
        db_session.rollback()
        raced = repository.find_by_idempotency_key(
            review.session_id,
            idempotency_key,
        )
        if raced is not None:
            return raced
        raise ConflictError(
            code="REVIEW_ALREADY_RUNNING",
            message="이미 실행 중인 검토가 있습니다.",
        ) from error
    return retried
