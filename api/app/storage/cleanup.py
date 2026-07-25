"""세션 수명주기에 맞춰 파일과 민감한 검토 데이터를 정리한다."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.db.database import Database
from app.idempotency.service import delete_expired_records
from app.review_sessions.domain import ReviewSessionState
from app.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.reviews.domain import ReviewState
from app.reviews.repository import SqlAlchemyReviewRepository
from app.storage.protocol import FileStorage


@dataclass(frozen=True, slots=True)
class CleanupResult:
    """정리 작업에서 만료·고아 파일을 처리한 건수."""

    expired_sessions: int
    orphan_files: int
    deleted_tombstones: int = 0
    deleted_idempotency_records: int = 0


class SessionFileLifecycle:
    """재시도 가능 여부와 세션 만료에 따른 파일 보존 정책."""

    def __init__(
        self,
        database: Database,
        storage: FileStorage,
        *,
        tombstone_ttl_seconds: int = 24 * 60 * 60,
    ) -> None:
        self._database = database
        self._storage = storage
        self._tombstone_ttl_seconds = tombstone_ttl_seconds

    def handle_review_failure(
        self,
        session_id: str,
        *,
        retryable: bool,
    ) -> bool:
        """재시도 불가능 실패의 파일만 즉시 폐기한다."""
        if retryable:
            return False

        with self._database.session() as db_session:
            repository = SqlAlchemyReviewSessionRepository(db_session)
            entity = repository.get(session_id)
            if entity is None or entity.storage_key is None:
                return False
            self._storage.delete(entity.storage_key)
            entity.storage_key = None
            entity.updated_at = datetime.now(UTC)
            repository.save(entity)
            db_session.commit()
            return True

    def cleanup_expired_and_orphaned(
        self,
        *,
        now: datetime | None = None,
        remove_orphans: bool = True,
    ) -> CleanupResult:
        """만료 세션의 데이터와 DB가 참조하지 않는 파일을 정리한다."""
        cleanup_time = now or datetime.now(UTC)
        expired_count = 0
        tombstone_count = 0
        idempotency_count = 0

        with self._database.session() as db_session:
            session_repository = SqlAlchemyReviewSessionRepository(db_session)
            review_repository = SqlAlchemyReviewRepository(db_session)
            for entity in session_repository.list_expired(cleanup_time):
                if review_repository.has_active_for_session(entity.id):
                    continue

                if entity.storage_key is not None:
                    self._storage.delete(entity.storage_key)
                entity.storage_key = None
                entity.scope_result = None
                entity.state = ReviewSessionState.EXPIRED
                entity.updated_at = cleanup_time
                session_repository.save(entity)

                for review in review_repository.list_by_session(entity.id):
                    review.state = ReviewState.EXPIRED
                    review.progress = None
                    review.result = None
                    review.error = None
                    review_repository.save(review)
                expired_count += 1
            idempotency_count = delete_expired_records(db_session, cleanup_time)
            tombstone_cutoff = cleanup_time - timedelta(
                seconds=self._tombstone_ttl_seconds
            )
            for entity in session_repository.list_expired_tombstones(
                tombstone_cutoff
            ):
                if session_repository.delete(entity.id):
                    tombstone_count += 1
            db_session.commit()

        orphan_count = 0
        if remove_orphans:
            with self._database.session() as db_session:
                referenced_keys = SqlAlchemyReviewSessionRepository(
                    db_session
                ).list_storage_keys()
            for storage_key in self._storage.list_keys():
                if storage_key not in referenced_keys:
                    self._storage.delete(storage_key)
                    orphan_count += 1

        return CleanupResult(
            expired_sessions=expired_count,
            orphan_files=orphan_count,
            deleted_tombstones=tombstone_count,
            deleted_idempotency_records=idempotency_count,
        )
