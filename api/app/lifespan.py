"""FastAPI 애플리케이션이 공유하는 외부 자원의 수명주기를 관리한다."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

from fastapi import FastAPI

from app.config import API_ROOT, get_settings
from app.common.logging import log_event
from app.db.database import Database
from app.llm.mcp import open_workshield_mcp
from app.review_sessions.activity import resume_ttl_after_review
from app.reviews.domain import ReviewState
from app.reviews.repository import SqlAlchemyReviewRepository
from app.storage.cleanup import SessionFileLifecycle
from app.storage.local import LocalFileStorage


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


def _recover_interrupted_reviews(
    database: Database,
    *,
    ttl_seconds: int = 30 * 60,
) -> None:
    """서버 재시작으로 중단된 실행을 재시도 가능한 실패로 복구한다."""
    with database.session() as db_session:
        repository = SqlAlchemyReviewRepository(db_session)
        recovered_at = datetime.now(UTC)
        for review in repository.list_active():
            review.state = ReviewState.FAILED
            review.error = {
                "code": "REVIEW_INTERRUPTED",
                "retryable": True,
                "next_action": "RETRY_REVIEW",
            }
            review.completed_at = recovered_at
            repository.save(review)
            resume_ttl_after_review(
                db_session,
                review,
                ttl_seconds=ttl_seconds,
                now=recovered_at,
            )
        db_session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """SQLite와 MCP session을 API 애플리케이션 수명과 함께 관리한다."""
    settings = get_settings()
    database = Database(settings.database_url, echo=settings.database_echo)
    database.create_schema()
    _recover_interrupted_reviews(
        database,
        ttl_seconds=getattr(settings, "session_ttl_seconds", 30 * 60),
    )
    storage_root = settings.temp_upload_dir
    if not storage_root.is_absolute():
        storage_root = (API_ROOT / storage_root).resolve()
    file_storage = LocalFileStorage(storage_root)
    SessionFileLifecycle(
        database,
        file_storage,
        tombstone_ttl_seconds=getattr(
            settings,
            "expired_tombstone_ttl_seconds",
            24 * 60 * 60,
        ),
    ).cleanup_expired_and_orphaned()
    app.state.database = database
    app.state.file_storage = file_storage
    app.state.review_tasks = {}
    cleanup_task = asyncio.create_task(
        _periodic_storage_cleanup(
            database,
            file_storage,
            interval_seconds=settings.storage_cleanup_interval_seconds,
            tombstone_ttl_seconds=getattr(
                settings,
                "expired_tombstone_ttl_seconds",
                24 * 60 * 60,
            ),
        )
    )
    try:
        async with open_workshield_mcp(settings) as runtime:
            app.state.workshield_mcp = runtime
            try:
                yield
            finally:
                del app.state.workshield_mcp
    finally:
        for task in getattr(app.state, "review_tasks", {}).values():
            task.cancel()
        if hasattr(app.state, "review_tasks"):
            del app.state.review_tasks
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
        if hasattr(app.state, "file_storage"):
            del app.state.file_storage
        if hasattr(app.state, "database"):
            del app.state.database
        database.dispose()
