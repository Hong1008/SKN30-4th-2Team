"""명시적 세션 연장 정책을 검증한다."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.db.database import Database
from app.core.common.errors import ExpiredError
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


def test_extend_review_session_rejects_expired_session(
    database: Database,
) -> None:
    """진행 중인 review가 있어도 만료 세션은 사용자 연장으로 되살릴 수 없다."""
    review_session = review_session_entity("ses_expired_extend")
    review_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    review = review_entity("rev_active_extend", session_id=review_session.id)

    with database.session() as db_session:
        SqlAlchemyReviewSessionRepository(db_session).add(review_session)
        db_session.commit()
        SqlAlchemyReviewRepository(db_session).add(review)
        db_session.commit()

        with pytest.raises(ExpiredError, match="만료"):
            extend_review_session(
                db_session,
                review_session,
                ttl_seconds=30 * 60,
            )
