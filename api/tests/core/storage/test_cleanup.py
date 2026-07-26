"""세션 만료와 재시도 정책에 따른 파일 정리를 검증한다."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

from app.core.db.database import Database
from app.domains.review_sessions.domain import ReviewSessionState
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.domains.reviews.domain import ReviewState
from app.domains.reviews.repository import SqlAlchemyReviewRepository
from app.core.storage.cleanup import SessionFileLifecycle
from app.core.storage.local import LocalFileStorage
from tests.domains.review_sessions.test_repository import review_session_entity
from tests.domains.reviews.test_repository import review_entity


def _seed_session_with_file(
    database: Database,
    storage: LocalFileStorage,
    *,
    session_id: str,
    expires_at: datetime,
    review_state: ReviewState = ReviewState.COMPLETED,
) -> tuple[str, str]:
    storage_key = storage.save(BytesIO(b"contract"), extension="pdf")
    entity = review_session_entity(session_id)
    entity.storage_key = storage_key
    entity.expires_at = expires_at
    review = review_entity(
        f"rev_{session_id}",
        session_id=session_id,
        state=review_state,
        result={"sensitive": "result"},
    )
    review.expires_at = expires_at
    with database.session() as session:
        SqlAlchemyReviewSessionRepository(session).add(entity)
        session.commit()
        SqlAlchemyReviewRepository(session).add(review)
        session.commit()
    return storage_key, review.id


def test_expired_session_removes_file_and_sensitive_result(
    database: Database,
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")
    now = datetime.now(UTC)
    storage_key, review_id = _seed_session_with_file(
        database,
        storage,
        session_id="ses_expired",
        expires_at=now - timedelta(seconds=1),
    )

    result = SessionFileLifecycle(
        database,
        storage,
    ).cleanup_expired_and_orphaned(now=now)

    assert result.expired_sessions == 1
    assert storage_key not in storage.list_keys()
    with database.session() as session:
        expired_session = SqlAlchemyReviewSessionRepository(session).get(
            "ses_expired"
        )
        expired_review = SqlAlchemyReviewRepository(session).get(review_id)
    assert expired_session is not None
    assert expired_session.state is ReviewSessionState.EXPIRED
    assert expired_session.storage_key is None
    assert expired_review is not None
    assert expired_review.state is ReviewState.EXPIRED
    assert expired_review.result is None


def test_cleanup_skips_review_already_expired_by_new_review_creation(
    database: Database,
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")
    now = datetime.now(UTC)
    storage_key = storage.save(BytesIO(b"contract"), extension="pdf")
    entity = review_session_entity("ses_mixed_expired")
    entity.storage_key = storage_key
    entity.expires_at = now - timedelta(seconds=1)
    already_expired = review_entity(
        "rev_already_expired",
        session_id=entity.id,
        idempotency_key="old",
        state=ReviewState.CANCELLED,
    )
    already_expired.expire(at=now - timedelta(minutes=1))
    terminal = review_entity(
        "rev_terminal",
        session_id=entity.id,
        idempotency_key="new",
        state=ReviewState.COMPLETED,
        result={"sensitive": "result"},
    )
    with database.session() as session:
        SqlAlchemyReviewSessionRepository(session).add(entity)
        session.commit()
        repository = SqlAlchemyReviewRepository(session)
        repository.add(already_expired)
        repository.add(terminal)
        session.commit()

    result = SessionFileLifecycle(
        database,
        storage,
    ).cleanup_expired_and_orphaned(now=now)

    assert result.expired_sessions == 1
    with database.session() as session:
        reviews = SqlAlchemyReviewRepository(session).list_by_session(entity.id)
    assert [review.state for review in reviews] == [
        ReviewState.EXPIRED,
        ReviewState.EXPIRED,
    ]


def test_active_review_prevents_expiration_cleanup(
    database: Database,
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")
    now = datetime.now(UTC)
    storage_key, _ = _seed_session_with_file(
        database,
        storage,
        session_id="ses_active",
        expires_at=now - timedelta(seconds=1),
        review_state=ReviewState.REVIEWING,
    )

    result = SessionFileLifecycle(
        database,
        storage,
    ).cleanup_expired_and_orphaned(now=now)

    assert result.expired_sessions == 0
    assert storage_key in storage.list_keys()


def test_startup_cleanup_deletes_orphan_and_is_idempotent(
    database: Database,
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")
    storage.save(BytesIO(b"orphan"), extension="pdf")
    lifecycle = SessionFileLifecycle(database, storage)

    first = lifecycle.cleanup_expired_and_orphaned()
    second = lifecycle.cleanup_expired_and_orphaned()

    assert first.orphan_files == 1
    assert second.orphan_files == 0


def test_only_non_retryable_failure_discards_file(
    database: Database,
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")
    expires_at = datetime.now(UTC) + timedelta(minutes=30)
    retryable_key, _ = _seed_session_with_file(
        database,
        storage,
        session_id="ses_retryable",
        expires_at=expires_at,
    )
    discarded_key, _ = _seed_session_with_file(
        database,
        storage,
        session_id="ses_non_retryable",
        expires_at=expires_at,
    )
    lifecycle = SessionFileLifecycle(database, storage)

    assert lifecycle.handle_review_failure(
        "ses_retryable",
        retryable=True,
    ) is False
    assert lifecycle.handle_review_failure(
        "ses_non_retryable",
        retryable=False,
    ) is True

    assert retryable_key in storage.list_keys()
    assert discarded_key not in storage.list_keys()
