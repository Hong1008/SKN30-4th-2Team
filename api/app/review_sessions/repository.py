"""검토 세션 Repository 계약과 SQLAlchemy 구현."""

from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ReviewSessionRow
from app.review_sessions.domain import ReviewSession
from app.review_sessions.mapper import (
    review_session_from_row,
    review_session_to_row,
    update_review_session_row,
)


class ReviewSessionRepository(Protocol):
    """Application Service가 의존할 검토 세션 저장 계약."""

    def add(self, entity: ReviewSession) -> None: ...

    def get(self, session_id: str) -> ReviewSession | None: ...

    def get_owned(
        self,
        session_id: str,
        access_token_hash: str,
    ) -> ReviewSession | None: ...

    def save(self, entity: ReviewSession) -> None: ...

    def list_expired(self, now: datetime) -> list[ReviewSession]: ...

    def list_expired_tombstones(self, cutoff: datetime) -> list[ReviewSession]: ...

    def list_storage_keys(self) -> set[str]: ...

    def delete(self, session_id: str) -> bool: ...


class SqlAlchemyReviewSessionRepository:
    """파일형 SQLite를 사용하는 검토 세션 Repository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entity: ReviewSession) -> None:
        self._session.add(review_session_to_row(entity))

    def get(self, session_id: str) -> ReviewSession | None:
        row = self._session.get(ReviewSessionRow, session_id)
        return review_session_from_row(row) if row is not None else None

    def get_owned(
        self,
        session_id: str,
        access_token_hash: str,
    ) -> ReviewSession | None:
        statement = select(ReviewSessionRow).where(
            ReviewSessionRow.id == session_id,
            ReviewSessionRow.access_token_hash == access_token_hash,
        )
        row = self._session.scalar(statement)
        return review_session_from_row(row) if row is not None else None

    def save(self, entity: ReviewSession) -> None:
        row = self._session.get(ReviewSessionRow, entity.id)
        if row is None:
            raise LookupError(f"검토 세션을 찾을 수 없습니다: {entity.id}")
        update_review_session_row(row, entity)

    def list_expired(self, now: datetime) -> list[ReviewSession]:
        statement = select(ReviewSessionRow).where(
            ReviewSessionRow.expires_at <= now,
            ReviewSessionRow.state != "EXPIRED",
        )
        return [
            review_session_from_row(row)
            for row in self._session.scalars(statement).all()
        ]

    def list_expired_tombstones(self, cutoff: datetime) -> list[ReviewSession]:
        statement = select(ReviewSessionRow).where(
            ReviewSessionRow.state == "EXPIRED",
            ReviewSessionRow.updated_at <= cutoff,
        )
        return [
            review_session_from_row(row)
            for row in self._session.scalars(statement).all()
        ]

    def list_storage_keys(self) -> set[str]:
        statement = select(ReviewSessionRow.storage_key).where(
            ReviewSessionRow.storage_key.is_not(None)
        )
        return {
            storage_key
            for storage_key in self._session.scalars(statement)
            if storage_key is not None
        }

    def delete(self, session_id: str) -> bool:
        row = self._session.get(ReviewSessionRow, session_id)
        if row is None:
            return False
        self._session.delete(row)
        return True
