"""파일형 SQLite Engine과 Session 수명주기를 검증한다."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from app.core.db.database import Database
from app.core.db.dependencies import get_db_session
from app.core.db.models import ReviewSessionRow
from app.domains.reviews.domain import ReviewState


def session_row(session_id: str = "ses_database") -> ReviewSessionRow:
    """DB 기반 테스트에 사용할 최소 검토 세션 Row를 만든다."""
    now = datetime.now(UTC)
    return ReviewSessionRow(
        id=session_id,
        access_token_hash=f"hash-{session_id}",
        state="ANALYZING_CONTRACT_TYPE",
        original_file_name="contract.pdf",
        file_size_bytes=1024,
        storage_key=f"{'a' * 43}.pdf",
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
    )


def test_create_schema_uses_file_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "workshield.db"
    database = Database(f"sqlite+pysqlite:///{database_path}")

    database.create_schema()

    assert database_path.is_file()
    assert set(inspect(database.engine).get_table_names()) == {
        "idempotency_records",
        "review_sessions",
        "reviews",
    }
    database.dispose()


def test_sqlite_foreign_keys_are_enabled(database: Database) -> None:
    with database.engine.connect() as connection:
        enabled = connection.scalar(text("PRAGMA foreign_keys"))

    assert enabled == 1


def test_database_readiness_executes_connection_check(database: Database) -> None:
    assert database.is_ready() is True


def test_file_database_survives_engine_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "persistent.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    first_database = Database(database_url)
    first_database.create_schema()
    with first_database.session() as session:
        session.add(session_row())
        session.commit()
    first_database.dispose()

    second_database = Database(database_url)
    second_database.create_schema()
    with second_database.session() as session:
        restored = session.get(ReviewSessionRow, "ses_database")
    second_database.dispose()

    assert restored is not None
    assert restored.original_file_name == "contract.pdf"


def test_db_session_dependency_rolls_back_on_error(database: Database) -> None:
    session_iterator = get_db_session(database)
    session = next(session_iterator)
    session.add(session_row("ses_rollback"))
    session.flush()

    with pytest.raises(RuntimeError, match="service failed"):
        session_iterator.throw(RuntimeError("service failed"))

    with database.session() as verification_session:
        assert verification_session.get(ReviewSessionRow, "ses_rollback") is None


def test_legacy_duplicate_active_reviews_use_normal_recovery_before_index(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-duplicates.db"
    database = Database(f"sqlite+pysqlite:///{database_path}")
    database.create_schema()
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP INDEX uq_reviews_one_active_per_session"
        )

    from app.domains.review_sessions.repository import (
        SqlAlchemyReviewSessionRepository,
    )
    from app.domains.reviews.repository import SqlAlchemyReviewRepository
    from app.lifespan import _recover_interrupted_reviews
    from tests.domains.review_sessions.test_repository import review_session_entity
    from tests.domains.reviews.test_repository import review_entity

    parent = review_session_entity("ses_duplicate")
    parent.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    first = review_entity(
        "rev_1",
        session_id=parent.id,
        idempotency_key="one",
        state=ReviewState.QUEUED,
    )
    second = review_entity(
        "rev_2",
        session_id=parent.id,
        idempotency_key="two",
        state=ReviewState.REVIEWING,
    )
    with database.session() as session:
        SqlAlchemyReviewSessionRepository(session).add(parent)
        session.commit()
        repository = SqlAlchemyReviewRepository(session)
        repository.add(first)
        repository.add(second)
        session.commit()

    database.create_schema()
    with database.engine.connect() as before_recovery:
        assert not any(
            row[1] == "uq_reviews_one_active_per_session"
            for row in before_recovery.exec_driver_sql(
                "PRAGMA index_list('reviews')"
            ).all()
        )

    recovered_at = datetime.now(UTC)
    _recover_interrupted_reviews(database, ttl_seconds=600)
    database.ensure_review_active_index()

    with database.session() as verification:
        reviews = SqlAlchemyReviewRepository(verification).list_by_session(
            parent.id
        )
        restored_parent = SqlAlchemyReviewSessionRepository(verification).get(
            parent.id
        )
    with database.engine.connect() as connection:
        indexes = connection.exec_driver_sql(
            "PRAGMA index_list('reviews')"
        ).all()
    database.dispose()
    assert [review.state for review in reviews] == [
        ReviewState.FAILED,
        ReviewState.FAILED,
    ]
    assert all(review.error["retryable"] is True for review in reviews)
    assert all(review.result is None for review in reviews)
    assert restored_parent is not None
    assert restored_parent.expires_at >= recovered_at + timedelta(seconds=599)
    assert any(
        row[1] == "uq_reviews_one_active_per_session" and row[2] == 1
        for row in indexes
    )
