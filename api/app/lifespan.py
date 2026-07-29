"""FastAPI 애플리케이션이 공유하는 외부 자원의 수명주기를 관리한다."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from app.config import API_ROOT, get_settings
from app.core.common.logging import log_event
from app.core.db.database import Database
from app.core.llm.mcp import open_workshield_mcp
from app.domains.review_sessions.activity import resume_ttl_after_review
from app.domains.reviews.repository import SqlAlchemyReviewRepository
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
            review.mark_interrupted(at=recovered_at)
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
    database = Database(settings.database_url, echo=settings.database_echo)
    database.create_schema()
    _recover_interrupted_reviews(
        database,
        ttl_seconds=review_session_policy.session_ttl_seconds,
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
    app.state.review_tasks = {}
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
            try:
                yield
            finally:
                review_tasks = list(
                    getattr(app.state, "review_tasks", {}).values()
                )
                for task in review_tasks:
                    task.cancel()
                await asyncio.gather(*review_tasks, return_exceptions=True)
                del app.state.workshield_mcp
    finally:
        if hasattr(app.state, "review_tasks"):
            del app.state.review_tasks
        cleanup_task.cancel()
        await asyncio.gather(cleanup_task, return_exceptions=True)
        if hasattr(app.state, "file_storage"):
            del app.state.file_storage
        if hasattr(app.state, "database"):
            del app.state.database
        database.dispose()
