"""마지막 사용자 활동 기준 sliding TTL 갱신."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.domains.review_sessions.domain import ReviewSession
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.domains.reviews.domain import Review, ReviewState
from app.domains.reviews.repository import (
    ConcurrentReviewUpdateError,
    SqlAlchemyReviewRepository,
)


def touch_session(
    db_session: Session,
    session: ReviewSession,
    *,
    ttl_seconds: int,
    now: datetime | None = None,
) -> ReviewSession:
    """세션의 마지막 활동과 만료 시각을 갱신한다."""
    touched_at = now or datetime.now(UTC)
    session.updated_at = touched_at
    session.expires_at = touched_at + timedelta(seconds=ttl_seconds)
    SqlAlchemyReviewSessionRepository(db_session).save(session)
    return session


def touch_review(
    db_session: Session,
    review: Review,
    *,
    ttl_seconds: int,
    now: datetime | None = None,
) -> Review:
    """review와 부모 세션의 TTL을 함께 연장한다."""
    touched_at = now or datetime.now(UTC)
    review.expires_at = touched_at + timedelta(seconds=ttl_seconds)
    review_repository = SqlAlchemyReviewRepository(db_session)
    try:
        review_repository.save(review)
    except ConcurrentReviewUpdateError:
        db_session.rollback()
        current = review_repository.get(review.id)
        if current is None:
            raise
        current.expires_at = touched_at + timedelta(seconds=ttl_seconds)
        review_repository.save(current)
        review = current
    session_repository = SqlAlchemyReviewSessionRepository(db_session)
    session = session_repository.get(review.session_id)
    if session is not None:
        touch_session(
            db_session,
            session,
            ttl_seconds=ttl_seconds,
            now=touched_at,
        )
    return review


def resume_ttl_after_review(
    db_session: Session,
    review: Review,
    *,
    ttl_seconds: int,
    now: datetime | None = None,
) -> None:
    """실행 종료 시 완료·실패 결과와 부모 세션의 TTL을 다시 시작한다."""
    if review.state in {ReviewState.QUEUED, ReviewState.REVIEWING}:
        return
    touch_review(
        db_session,
        review,
        ttl_seconds=ttl_seconds,
        now=now,
    )


def extend_review_session(
    db_session: Session,
    session: ReviewSession,
    *,
    ttl_seconds: int,
    now: datetime | None = None,
) -> ReviewSession:
    """사용자 연장 요청으로 세션과 최신 검토의 만료 시각을 함께 재설정한다."""
    touched_at = now or datetime.now(UTC)
    reviews = SqlAlchemyReviewRepository(db_session).list_by_session(session.id)
    extendable_reviews = [
        review for review in reviews if review.state is not ReviewState.EXPIRED
    ]
    if extendable_reviews:
        touch_review(
            db_session,
            extendable_reviews[-1],
            ttl_seconds=ttl_seconds,
            now=touched_at,
        )
    else:
        touch_session(
            db_session,
            session,
            ttl_seconds=ttl_seconds,
            now=touched_at,
        )
    extended = SqlAlchemyReviewSessionRepository(db_session).get(session.id)
    if extended is None:
        raise LookupError(f"검토 세션을 찾을 수 없습니다: {session.id}")
    return extended
