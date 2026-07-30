"""FastAPI 애플리케이션이 공유하는 외부 자원의 수명주기를 관리한다."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from app.config import API_ROOT, MCPTransport, get_settings
from app.core.admission.gate import BoundedFifoGate, ImmediateConcurrencyLimiter
from app.core.admission.policy import (
    REVIEW_POLICY,
    SUGGESTION_POLICY,
    UPLOAD_POLICY,
)
from app.core.common.logging import log_event
from app.core.db.database import Database
from app.core.llm.mcp import open_workshield_mcp
from app.domains.review_sessions.activity import resume_ttl_after_review
from app.domains.reviews.repository import SqlAlchemyReviewRepository
from app.domains.reviews.runner import execute_review
from app.domains.reviews.scheduler import ReviewScheduler
from app.core.storage.cleanup import SessionFileLifecycle
from app.core.storage.local import LocalFileStorage
from app.core.storage.policy import DEFAULT_STORAGE_POLICY, StoragePolicy
from app.domains.review_sessions.policy import (
    DEFAULT_REVIEW_SESSION_POLICY,
    ReviewSessionPolicy,
)


async def _periodic_storage_cleanup(
    database: Database,
    file_storage: LocalFileStorage,
    *,
    interval_seconds: int,
    tombstone_ttl_seconds: int,
) -> None:
    """실행 중에도 만료 세션을 주기적으로 정리한다."""
    lifecycle = SessionFileLifecycle(
        database,
        file_storage,
        tombstone_ttl_seconds=tombstone_ttl_seconds,
    )
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await asyncio.to_thread(
                lifecycle.cleanup_expired_and_orphaned,
                remove_orphans=False,
            )
        except Exception:
            log_event(
                event="storage.cleanup.failed",
                request_id="system",
                state="failed",
                level=logging.ERROR,
            )


def _recover_reviewing(
    database: Database,
    *,
    ttl_seconds: int = 30 * 60,
) -> None:
    """서버 재시작으로 중단된 실행을 재시도 가능한 실패로 복구한다."""
    with database.session() as db_session:
        repository = SqlAlchemyReviewRepository(db_session)
        recovered_at = datetime.now(UTC)
        for review in repository.list_reviewing():
            review.mark_interrupted(at=recovered_at)
            repository.save(review)
            resume_ttl_after_review(
                db_session,
                review,
                ttl_seconds=ttl_seconds,
                now=recovered_at,
            )
        db_session.commit()


# 이전 내부 이름을 사용하는 테스트·호출자의 호환성을 유지한다.
_recover_interrupted_reviews = _recover_reviewing


def _fail_queue_recovery_overflow(
    database: Database,
    *,
    capacity: int,
) -> int:
    """복구 용량을 넘은 최신 QUEUED를 재시도 가능한 실패로 전환한다."""
    with database.session() as db_session:
        repository = SqlAlchemyReviewRepository(db_session)
        queued = repository.list_queued()
        overflow = queued[capacity:]
        failed_at = datetime.now(UTC)
        for review in overflow:
            review.fail(
                {
                    "code": "REVIEW_QUEUE_RECOVERY_OVERFLOW",
                    "retryable": True,
                    "next_action": "RETRY_REVIEW",
                },
                at=failed_at,
            )
            repository.save(review)
        db_session.commit()
    return len(overflow)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """SQLite와 MCP session을 API 애플리케이션 수명과 함께 관리한다."""
    settings = get_settings()
    review_session_policy = getattr(
        app.state,
        "review_session_policy",
        DEFAULT_REVIEW_SESSION_POLICY,
    )
    storage_policy = getattr(
        app.state,
        "storage_policy",
        DEFAULT_STORAGE_POLICY,
    )
    if not isinstance(review_session_policy, ReviewSessionPolicy):
        raise TypeError("review_session_policy는 ReviewSessionPolicy여야 합니다.")
    if not isinstance(storage_policy, StoragePolicy):
        raise TypeError("storage_policy는 StoragePolicy여야 합니다.")
    database = Database(
        settings.database_url,
        echo=settings.database_echo,
        busy_timeout_ms=getattr(settings, "sqlite_busy_timeout_ms", 5000),
    )
    database.create_schema()
    _recover_reviewing(
        database,
        ttl_seconds=review_session_policy.session_ttl_seconds,
    )
    _fail_queue_recovery_overflow(
        database,
        capacity=REVIEW_POLICY.queue_capacity,
    )
    database.ensure_review_active_index()
    storage_root = review_session_policy.temp_upload_dir
    if not storage_root.is_absolute():
        storage_root = (API_ROOT / storage_root).resolve()
    file_storage = LocalFileStorage(storage_root)
    SessionFileLifecycle(
        database,
        file_storage,
        tombstone_ttl_seconds=storage_policy.expired_tombstone_ttl_seconds,
    ).cleanup_expired_and_orphaned()
    app.state.database = database
    app.state.file_storage = file_storage
    app.state.suggestion_gate = BoundedFifoGate(
        SUGGESTION_POLICY,
        error_code="SUGGESTION_QUEUE_FULL",
        error_message="현재 제안 생성 요청이 많습니다. 잠시 후 다시 시도해 주세요.",
    )
    app.state.upload_limiter = ImmediateConcurrencyLimiter(
        UPLOAD_POLICY,
        error_code="UPLOAD_CAPACITY_EXCEEDED",
        error_message="현재 업로드 요청이 많습니다. 잠시 후 다시 시도해 주세요.",
    )
    cleanup_task = asyncio.create_task(
        _periodic_storage_cleanup(
            database,
            file_storage,
            interval_seconds=storage_policy.cleanup_interval_seconds,
            tombstone_ttl_seconds=storage_policy.expired_tombstone_ttl_seconds,
        )
    )
    try:
        async with open_workshield_mcp(settings) as runtime:
            app.state.workshield_mcp = runtime
            scheduler = ReviewScheduler(
                database,
                lambda review_id: execute_review(
                    database=database,
                    storage=file_storage,
                    runtime=runtime,
                    settings=settings,
                    review_id=review_id,
                    policy=review_session_policy,
                    runtime_factory=(
                        (lambda: open_workshield_mcp(settings))
                        if settings.workshield_mcp_transport is MCPTransport.STDIO
                        else None
                    ),
                ),
                REVIEW_POLICY,
            )
            app.state.review_scheduler = scheduler
            await scheduler.reconcile()
            await scheduler.start()
            try:
                yield
            finally:
                await scheduler.stop()
                _recover_reviewing(
                    database,
                    ttl_seconds=review_session_policy.session_ttl_seconds,
                )
                del app.state.review_scheduler
                del app.state.workshield_mcp
    finally:
        if hasattr(app.state, "suggestion_gate"):
            del app.state.suggestion_gate
        if hasattr(app.state, "upload_limiter"):
            del app.state.upload_limiter
        cleanup_task.cancel()
        await asyncio.gather(cleanup_task, return_exceptions=True)
        if hasattr(app.state, "file_storage"):
            del app.state.file_storage
        if hasattr(app.state, "database"):
            del app.state.database
        database.dispose()
