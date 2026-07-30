"""명시적 세션 연장 정책을 검증한다."""

from datetime import UTC, datetime, timedelta

from app.core.db.database import Database
from app.domains.review_sessions.activity import extend_review_session
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.domains.reviews.repository import SqlAlchemyReviewRepository
from tests.domains.review_sessions.test_repository import review_session_entity
from tests.domains.reviews.test_repository import review_entity


def test_extend_review_session_resets_latest_review_and_parent(
    database: Database,
) -> None:
    """연장은 부모 세션과 현재 review를 같은 30분 만료시각으로 맞춘다."""
    review_session = review_session_entity("ses_extend")
    review = review_entity("rev_extend", session_id=review_session.id)
    now = datetime.now(UTC)
    expected_expiration = now + timedelta(minutes=30)

    with database.session() as db_session:
        SqlAlchemyReviewSessionRepository(db_session).add(review_session)
        db_session.commit()
        SqlAlchemyReviewRepository(db_session).add(review)
        db_session.commit()

        extended = extend_review_session(
            db_session,
            review_session,
            ttl_seconds=30 * 60,
            now=now,
        )
        db_session.commit()

    with database.session() as db_session:
        restored_review = SqlAlchemyReviewRepository(db_session).get(review.id)
    assert restored_review is not None
    assert extended.expires_at == expected_expiration
    assert restored_review.expires_at == expected_expiration
