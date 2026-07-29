"""검토 생성·재시도 use case의 핵심 불변식을 검증한다."""

from datetime import UTC, datetime

import pytest

from app.core.common.errors import ConflictError
from app.core.db.database import Database
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.domains.reviews.domain import ReviewState
from app.domains.reviews.repository import SqlAlchemyReviewRepository
from app.domains.reviews.service import retry_review
from tests.domains.review_sessions.test_repository import review_session_entity
from tests.domains.reviews.test_repository import review_entity


def test_retry_creates_new_review_and_blocks_second_active_retry(
    database: Database,
) -> None:
    session = review_session_entity("ses_retry")
    source = review_entity(
        "rev_failed_source",
        session_id=session.id,
        state=ReviewState.QUEUED,
    )
    source.fail(
        {
            "code": "PIPELINE_ERROR",
            "retryable": True,
            "next_action": "RETRY_REVIEW",
        },
        at=datetime.now(UTC),
    )
    with database.session() as db_session:
        SqlAlchemyReviewSessionRepository(db_session).add(session)
        db_session.commit()
        repository = SqlAlchemyReviewRepository(db_session)
        repository.add(source)
        db_session.commit()

        retried = retry_review(
            db_session,
            source,
            idempotency_key="retry-one",
        )
        db_session.commit()

        restored_source = repository.get(source.id)
        assert restored_source is not None
        assert restored_source.state is ReviewState.FAILED
        assert retried.id != source.id
        assert retried.retry_of_review_id == source.id
        assert retried.state is ReviewState.QUEUED

        with pytest.raises(ConflictError) as error:
            retry_review(
                db_session,
                source,
                idempotency_key="retry-two",
            )
        assert error.value.code == "REVIEW_ALREADY_RUNNING"


def test_retry_unique_race_reconciles_same_operation_review(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = review_session_entity("ses_retry_race")
    source = review_entity(
        "rev_retry_race_source",
        session_id=session.id,
        state=ReviewState.QUEUED,
    )
    source.fail(
        {"code": "PIPELINE_ERROR", "retryable": True},
        at=datetime.now(UTC),
    )
    winner = review_entity(
        "rev_retry_race_winner",
        session_id=session.id,
        idempotency_key="same-operation",
        state=ReviewState.QUEUED,
    )
    winner.retry_of_review_id = source.id
    with database.session() as setup:
        SqlAlchemyReviewSessionRepository(setup).add(session)
        setup.commit()
        repository = SqlAlchemyReviewRepository(setup)
        repository.add(source)
        repository.add(winner)
        setup.commit()

    original_find = SqlAlchemyReviewRepository.find_by_idempotency_key
    calls = 0

    def raced_find(repository, session_id, idempotency_key):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return original_find(repository, session_id, idempotency_key)

    monkeypatch.setattr(
        SqlAlchemyReviewRepository,
        "find_by_idempotency_key",
        raced_find,
    )
    monkeypatch.setattr(
        SqlAlchemyReviewRepository,
        "has_active_for_session",
        lambda repository, session_id: False,
    )
    with database.session() as request:
        reconciled = retry_review(
            request,
            source,
            idempotency_key="same-operation",
        )

    assert reconciled.id == winner.id
