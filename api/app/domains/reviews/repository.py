"""검토 Repository 계약과 SQLAlchemy 구현."""

from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.db.models import ReviewRow
from app.core.db.models import ReviewSessionRow
from app.domains.reviews.domain import Review
from app.domains.reviews.mapper import review_from_row, review_to_row


class ConcurrentReviewUpdateError(RuntimeError):
    """다른 트랜잭션이 먼저 Review를 변경했음을 나타낸다."""


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

    def count_queued(self) -> int: ...

    def list_queued(self, *, limit: int | None = None) -> list[Review]: ...

    def list_reviewing(self) -> list[Review]: ...

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
        expected_version = entity.version
        snapshot = review_to_row(entity)
        result = self._session.execute(
            update(ReviewRow)
            .where(
                ReviewRow.id == entity.id,
                ReviewRow.version == expected_version,
            )
            .values(
                session_id=snapshot.session_id,
                retry_of_review_id=snapshot.retry_of_review_id,
                idempotency_key=snapshot.idempotency_key,
                state=snapshot.state,
                version=expected_version + 1,
                mcp_review_status=snapshot.mcp_review_status,
                contract_type=snapshot.contract_type,
                progress=snapshot.progress,
                result=snapshot.result,
                error=snapshot.error,
                created_at=snapshot.created_at,
                started_at=snapshot.started_at,
                completed_at=snapshot.completed_at,
                expires_at=snapshot.expires_at,
            )
        )
        if result.rowcount != 1:
            raise ConcurrentReviewUpdateError(
                f"Review가 다른 작업에서 먼저 변경되었습니다: {entity.id}"
            )
        entity.version = expected_version + 1

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

    def count_queued(self) -> int:
        statement = select(func.count()).select_from(ReviewRow).where(
            ReviewRow.state == "QUEUED"
        )
        return int(self._session.scalar(statement) or 0)

    def list_queued(self, *, limit: int | None = None) -> list[Review]:
        statement = (
            select(ReviewRow)
            .where(ReviewRow.state == "QUEUED")
            .order_by(ReviewRow.created_at, ReviewRow.id)
        )
        if limit is not None:
            statement = statement.limit(limit)
        return [
            review_from_row(row)
            for row in self._session.scalars(statement).all()
        ]

    def list_reviewing(self) -> list[Review]:
        statement = (
            select(ReviewRow)
            .where(ReviewRow.state == "REVIEWING")
            .order_by(ReviewRow.created_at, ReviewRow.id)
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
