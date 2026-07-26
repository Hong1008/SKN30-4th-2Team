"""파일형 SQLite Engine과 SQLAlchemy Session factory를 관리한다."""

import sqlite3
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import API_ROOT
from app.core.db.base import Base


def _normalized_sqlite_url(database_url: str) -> str:
    """상대 SQLite 파일 경로를 API 프로젝트 기준 절대경로로 바꾼다."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError("DATABASE_URL은 SQLite URL이어야 합니다.")

    database_name = url.database
    if not database_name or database_name == ":memory:":
        raise ValueError("DATABASE_URL은 파일형 SQLite 경로여야 합니다.")

    database_path = Path(database_name)
    if not database_path.is_absolute():
        database_path = (API_ROOT / database_path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return url.set(database=str(database_path)).render_as_string(
        hide_password=False,
    )


def _enable_sqlite_foreign_keys(
    dbapi_connection: sqlite3.Connection,
    _connection_record: object,
) -> None:
    """각 SQLite 연결에서 외래키 제약을 활성화한다."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Database:
    """애플리케이션 수명 동안 공유하는 Engine과 Session factory."""

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        self.url = _normalized_sqlite_url(database_url)
        self.engine: Engine = create_engine(self.url, echo=echo)
        event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )

    def create_schema(self) -> None:
        """등록된 ORM 모델의 SQLite 테이블을 생성한다."""
        from app.core.db import models  # noqa: F401

        Base.metadata.create_all(self.engine)
        self._add_storage_key_to_legacy_schema()
        self._add_review_version_to_legacy_schema()
        if not self._has_duplicate_active_reviews():
            self.ensure_review_active_index()

    def _add_storage_key_to_legacy_schema(self) -> None:
        """초기 개발 DB의 storage_path를 건드리지 않고 새 컬럼을 추가한다."""
        inspector = inspect(self.engine)
        if "review_sessions" not in inspector.get_table_names():
            return
        column_names = {
            column["name"]
            for column in inspector.get_columns("review_sessions")
        }
        if "storage_key" in column_names:
            return
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE review_sessions "
                    "ADD COLUMN storage_key TEXT NULL"
                )
            )

    def _add_review_version_to_legacy_schema(self) -> None:
        """이전 개발 DB에 Review 낙관적 잠금 컬럼과 active 제약을 추가한다."""
        inspector = inspect(self.engine)
        if "reviews" not in inspector.get_table_names():
            return
        column_names = {
            column["name"] for column in inspector.get_columns("reviews")
        }
        with self.engine.begin() as connection:
            if "version" not in column_names:
                connection.execute(
                    text(
                        "ALTER TABLE reviews "
                        "ADD COLUMN version INTEGER NOT NULL DEFAULT 0"
                    )
                )
    def _has_duplicate_active_reviews(self) -> bool:
        """세션당 active Review가 둘 이상인 legacy 데이터인지 확인한다."""
        with self.engine.connect() as connection:
            return connection.scalar(
                text(
                    "SELECT 1 FROM reviews "
                    "WHERE state IN ('QUEUED', 'REVIEWING') "
                    "GROUP BY session_id HAVING COUNT(*) > 1 LIMIT 1"
                )
            ) is not None

    def ensure_review_active_index(self) -> None:
        """복구가 끝난 Review 테이블에 active 유일성 제약을 보장한다."""
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_reviews_one_active_per_session ON reviews(session_id) "
                    "WHERE state IN ('QUEUED', 'REVIEWING')"
                )
            )

    def session(self) -> Session:
        """명시적으로 닫아야 하는 새 SQLAlchemy Session을 반환한다."""
        return self.session_factory()

    def is_ready(self) -> bool:
        """새 연결에서 간단한 쿼리를 실행해 SQLite 준비 상태를 확인한다."""
        try:
            with self.engine.connect() as connection:
                return connection.scalar(text("SELECT 1")) == 1
        except SQLAlchemyError:
            return False

    def dispose(self) -> None:
        """Engine의 연결 풀을 정리한다."""
        self.engine.dispose()
