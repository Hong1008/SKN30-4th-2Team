"""검토 세션 Repository 계약과 SQLAlchemy 구현."""

from typing import Protocol

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

    def save(self, entity: ReviewSession) -> None: ...

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

    def save(self, entity: ReviewSession) -> None:
        row = self._session.get(ReviewSessionRow, entity.id)
        if row is None:
            raise LookupError(f"검토 세션을 찾을 수 없습니다: {entity.id}")
        update_review_session_row(row, entity)

    def delete(self, session_id: str) -> bool:
        row = self._session.get(ReviewSessionRow, session_id)
        if row is None:
            return False
        self._session.delete(row)
        return True
