"""API 테스트 전역 fixture."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.db.database import Database


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    """테스트마다 독립된 파일형 SQLite Database를 제공한다."""
    database_path = tmp_path / "workshield-test.db"
    test_database = Database(
        f"sqlite+pysqlite:///{database_path}",
        echo=False,
    )
    test_database.create_schema()
    try:
        yield test_database
    finally:
        test_database.dispose()
