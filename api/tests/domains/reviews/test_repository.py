"""검토 ORM 매핑과 Repository 계약을 검증한다."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db.database import Database
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.domains.reviews.domain import MCPReviewStatus, Review, ReviewState
from app.domains.reviews.mapper import review_from_row, review_to_row
from app.domains.reviews.repository import (
    ConcurrentReviewUpdateError,
    SqlAlchemyReviewRepository,
)
from tests.domains.review_sessions.test_repository import review_session_entity


def review_entity(
    review_id: str = "rev_repository",
    *,
    session_id: str = "ses_repository",
    idempotency_key: str = "idem-review",
    state: ReviewState = ReviewState.REVIEWING,
    result: dict[str, object] | None = None,
) -> Review:
    """Repository 테스트용 검토 엔티티를 만든다."""
    now = datetime.now(UTC)
    return Review.restore(
        review_id=review_id,
        session_id=session_id,
        idempotency_key=idempotency_key,
        state=state,
        contract_type="SW_FREELANCE",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        mcp_review_status=(
            MCPReviewStatus.OK if state is ReviewState.COMPLETED else None
        ),
        progress={
            "sequence": 0 if state is ReviewState.QUEUED else 1,
            "stage": "PREPARE",
            "percent": 0,
        },
        result=result,
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

        entity.complete(
            MCPReviewStatus.OK,
            {
                "summary": {"clause_results": {"total": 1}},
                "clause_results": [],
                "missing_standard_clauses": [],
            },
            at=datetime.now(UTC),
        )
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


def test_only_one_active_review_is_allowed_per_session(
    database: Database,
) -> None:
    review_session = review_session_entity("ses_one_active")
    first = review_entity(
        "rev_active_first",
        session_id=review_session.id,
        idempotency_key="first-key",
        state=ReviewState.QUEUED,
    )
    second = review_entity(
        "rev_active_second",
        session_id=review_session.id,
        idempotency_key="second-key",
        state=ReviewState.QUEUED,
    )
    with database.session() as session:
        SqlAlchemyReviewSessionRepository(session).add(review_session)
        session.commit()
        repository = SqlAlchemyReviewRepository(session)
        repository.add(first)
        session.commit()
        repository.add(second)
        with pytest.raises(IntegrityError):
            session.commit()


def test_stale_progress_cannot_overwrite_cancelled_review(
    database: Database,
) -> None:
    review_session = review_session_entity("ses_cas")
    entity = review_entity("rev_cas", session_id=review_session.id)
    with database.session() as setup:
        SqlAlchemyReviewSessionRepository(setup).add(review_session)
        setup.commit()
        SqlAlchemyReviewRepository(setup).add(entity)
        setup.commit()

    with database.session() as progress_session, database.session() as cancel_session:
        stale = SqlAlchemyReviewRepository(progress_session).get(entity.id)
        current = SqlAlchemyReviewRepository(cancel_session).get(entity.id)
        assert stale is not None
        assert current is not None
        current.cancel(at=datetime.now(UTC))
        SqlAlchemyReviewRepository(cancel_session).save(current)
        cancel_session.commit()

        stale.record_progress(
            stage="CLAUSE_REVIEW",
            current=1,
            total=2,
            message="늦게 도착한 진행률",
        )
        with pytest.raises(ConcurrentReviewUpdateError):
            SqlAlchemyReviewRepository(progress_session).save(stale)
        progress_session.rollback()

    with database.session() as verification:
        restored = SqlAlchemyReviewRepository(verification).get(entity.id)
    assert restored is not None
    assert restored.state is ReviewState.CANCELLED
    assert restored.progress is not None
    assert restored.progress["sequence"] == 2


def test_stale_completion_cannot_overwrite_cancelled_review(
    database: Database,
) -> None:
    review_session = review_session_entity("ses_completion_cas")
    entity = review_entity(
        "rev_completion_cas",
        session_id=review_session.id,
    )
    with database.session() as setup:
        SqlAlchemyReviewSessionRepository(setup).add(review_session)
        setup.commit()
        SqlAlchemyReviewRepository(setup).add(entity)
        setup.commit()

    with database.session() as runner_session, database.session() as cancel_session:
        stale_runner = SqlAlchemyReviewRepository(runner_session).get(entity.id)
        cancelling = SqlAlchemyReviewRepository(cancel_session).get(entity.id)
        assert stale_runner is not None
        assert cancelling is not None
        cancelling.cancel(at=datetime.now(UTC))
        SqlAlchemyReviewRepository(cancel_session).save(cancelling)
        cancel_session.commit()

        stale_runner.complete(
            MCPReviewStatus.OK,
            {"clause_results": [], "missing_standard_clauses": []},
            at=datetime.now(UTC),
        )
        with pytest.raises(ConcurrentReviewUpdateError):
            SqlAlchemyReviewRepository(runner_session).save(stale_runner)
        runner_session.rollback()

    with database.session() as verification:
        restored = SqlAlchemyReviewRepository(verification).get(entity.id)
    assert restored is not None
    assert restored.state is ReviewState.CANCELLED
    assert restored.result is None
