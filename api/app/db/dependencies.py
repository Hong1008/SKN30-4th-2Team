"""FastAPI에서 재사용할 Database와 Session 의존성을 정의한다."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db.database import Database


def get_database(request: Request) -> Database:
    """lifespan에서 준비한 Database를 반환한다."""
    database = getattr(request.app.state, "database", None)
    if not isinstance(database, Database):
        raise RuntimeError("Database가 준비되지 않았습니다.")
    return database


DatabaseDep = Annotated[Database, Depends(get_database)]


def get_db_session(database: DatabaseDep) -> Iterator[Session]:
    """요청 단위 Session을 제공하며 오류가 발생하면 rollback한다."""
    session = database.session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbSessionDep = Annotated[Session, Depends(get_db_session)]
