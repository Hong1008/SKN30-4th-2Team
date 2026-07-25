"""파일형 SQLite Engine과 Session 수명주기를 검증한다."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from app.db.database import Database
from app.db.dependencies import get_db_session
from app.db.models import ReviewSessionRow


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
