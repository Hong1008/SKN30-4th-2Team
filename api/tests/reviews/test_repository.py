"""검토 ORM 매핑과 Repository 계약을 검증한다."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.database import Database
from app.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.reviews.domain import MCPReviewStatus, Review, ReviewState
from app.reviews.mapper import review_from_row, review_to_row
from app.reviews.repository import SqlAlchemyReviewRepository
from tests.review_sessions.test_repository import review_session_entity


def review_entity(
    review_id: str = "rev_repository",
    *,
    session_id: str = "ses_repository",
    idempotency_key: str = "idem-review",
) -> Review:
    """Repository 테스트용 검토 엔티티를 만든다."""
    now = datetime.now(UTC)
    return Review(
        id=review_id,
        session_id=session_id,
        idempotency_key=idempotency_key,
        state=ReviewState.REVIEWING,
        contract_type="SW_FREELANCE",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        mcp_review_status=MCPReviewStatus.OK,
        progress={"sequence": 1, "stage": "PREPARE", "percent": 0},
    )


def test_review_mapper_round_trip() -> None:
    entity = review_entity()

    restored = review_from_row(review_to_row(entity))

    assert restored == entity


def test_review_repository_add_get_find_and_save(database: Database) -> None:
    review_session = review_session_entity()
    entity = review_entity()
    with database.session() as session:
        SqlAlchemyReviewSessionRepository(session).add(review_session)
        session.commit()
        repository = SqlAlchemyReviewRepository(session)
        repository.add(entity)
        session.commit()

        assert repository.get(entity.id) == entity
        assert (
            repository.find_by_idempotency_key(
                entity.session_id,
                entity.idempotency_key,
            )
            == entity
        )
        assert repository.list_by_session(entity.session_id) == [entity]

        entity.state = ReviewState.COMPLETED
        entity.result = {
            "summary": {"clause_results": {"total": 1}},
            "clause_results": [],
            "missing_standard_clauses": [],
        }
        entity.completed_at = datetime.now(UTC)
        repository.save(entity)
        session.commit()

    with database.session() as session:
        restored = SqlAlchemyReviewRepository(session).get(entity.id)

    assert restored == entity


def test_review_idempotency_key_is_unique_per_session(
    database: Database,
) -> None:
    review_session = review_session_entity("ses_idempotency")
    first = review_entity(
        "rev_first",
        session_id=review_session.id,
        idempotency_key="same-key",
    )
    second = review_entity(
        "rev_second",
        session_id=review_session.id,
        idempotency_key="same-key",
    )
    with database.session() as session:
        SqlAlchemyReviewSessionRepository(session).add(review_session)
        session.commit()
        repository = SqlAlchemyReviewRepository(session)
        repository.add(first)
        repository.add(second)

        with pytest.raises(IntegrityError):
            session.commit()
