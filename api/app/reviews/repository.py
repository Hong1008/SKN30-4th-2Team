"""검토 Repository 계약과 SQLAlchemy 구현."""

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ReviewRow
from app.db.models import ReviewSessionRow
from app.reviews.domain import Review
from app.reviews.mapper import review_from_row, review_to_row, update_review_row


class ReviewRepository(Protocol):
    """Application Service가 의존할 검토 저장 계약."""

    def add(self, entity: Review) -> None: ...

    def get(self, review_id: str) -> Review | None: ...

    def get_owned(
        self,
        review_id: str,
        access_token_hash: str,
    ) -> Review | None: ...

    def save(self, entity: Review) -> None: ...

    def find_by_idempotency_key(
        self,
        session_id: str,
        idempotency_key: str,
    ) -> Review | None: ...

    def list_by_session(self, session_id: str) -> list[Review]: ...

    def has_active_for_session(self, session_id: str) -> bool: ...

    def list_active(self) -> list[Review]: ...

    def delete(self, review_id: str) -> bool: ...


class SqlAlchemyReviewRepository:
    """파일형 SQLite를 사용하는 검토 Repository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entity: Review) -> None:
        self._session.add(review_to_row(entity))

    def get(self, review_id: str) -> Review | None:
        row = self._session.get(ReviewRow, review_id)
        return review_from_row(row) if row is not None else None

    def get_owned(
        self,
        review_id: str,
        access_token_hash: str,
    ) -> Review | None:
        statement = (
            select(ReviewRow)
            .join(ReviewSessionRow, ReviewSessionRow.id == ReviewRow.session_id)
            .where(
                ReviewRow.id == review_id,
                ReviewSessionRow.access_token_hash == access_token_hash,
            )
        )
        row = self._session.scalar(statement)
        return review_from_row(row) if row is not None else None

    def save(self, entity: Review) -> None:
        row = self._session.get(ReviewRow, entity.id)
        if row is None:
            raise LookupError(f"검토를 찾을 수 없습니다: {entity.id}")
        update_review_row(row, entity)

    def find_by_idempotency_key(
        self,
        session_id: str,
        idempotency_key: str,
    ) -> Review | None:
        statement = select(ReviewRow).where(
            ReviewRow.session_id == session_id,
            ReviewRow.idempotency_key == idempotency_key,
        )
        row = self._session.scalar(statement)
        return review_from_row(row) if row is not None else None

    def list_by_session(self, session_id: str) -> list[Review]:
        statement = (
            select(ReviewRow)
            .where(ReviewRow.session_id == session_id)
            .order_by(ReviewRow.created_at, ReviewRow.id)
        )
        return [
            review_from_row(row)
            for row in self._session.scalars(statement).all()
        ]

    def has_active_for_session(self, session_id: str) -> bool:
        statement = select(ReviewRow.id).where(
            ReviewRow.session_id == session_id,
            ReviewRow.state.in_(("QUEUED", "REVIEWING")),
        )
        return self._session.scalar(statement) is not None

    def list_active(self) -> list[Review]:
        statement = select(ReviewRow).where(
            ReviewRow.state.in_(("QUEUED", "REVIEWING")),
        )
        return [
            review_from_row(row)
            for row in self._session.scalars(statement).all()
        ]

    def delete(self, review_id: str) -> bool:
        row = self._session.get(ReviewRow, review_id)
        if row is None:
            return False
        self._session.delete(row)
        return True
