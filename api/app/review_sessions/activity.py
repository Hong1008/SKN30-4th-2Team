"""마지막 사용자 활동 기준 sliding TTL 갱신."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.review_sessions.domain import ReviewSession
from app.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.reviews.domain import Review, ReviewState
from app.reviews.repository import SqlAlchemyReviewRepository


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
    SqlAlchemyReviewRepository(db_session).save(review)
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
