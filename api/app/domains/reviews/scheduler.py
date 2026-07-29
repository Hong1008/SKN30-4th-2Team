"""SQLite QUEUED 원장을 실행하는 단일 검토 scheduler."""

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from app.core.admission.policy import QueuedAdmissionPolicy
from app.core.common.errors import OverCapacityError
from app.core.common.logging import log_event
from app.core.db.database import Database
from app.domains.reviews.domain import ReviewState
from app.domains.reviews.repository import SqlAlchemyReviewRepository


ReviewExecutor = Callable[[str], Awaitable[None]]


class ReviewScheduler:
    """DB 상태를 재확인하며 한 번에 하나의 검토만 실행한다."""

    def __init__(
        self,
        database: Database,
        executor: ReviewExecutor,
        policy: QueuedAdmissionPolicy,
    ) -> None:
        if policy.concurrency != 1:
            raise ValueError("ReviewScheduler concurrency는 1이어야 합니다.")
        self.database = database
        self.policy = policy
        self._executor = executor
        self._pending: deque[str] = deque()
        self._pending_set: set[str] = set()
        self._condition = asyncio.Condition()
        self.admission_lock = asyncio.Lock()
        self.worker_task: asyncio.Task[None] | None = None
        self.current_review_id: str | None = None
        self.current_execution_task: asyncio.Task[None] | None = None
        self._accepting = True

    @property
    def is_alive(self) -> bool:
        return self.worker_task is not None and not self.worker_task.done()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @asynccontextmanager
    async def admission(self) -> AsyncIterator[None]:
        """DB commit과 enqueue까지 신규 접수를 직렬화한다."""
        async with self.admission_lock:
            if not self._accepting:
                raise OverCapacityError(
                    code="REVIEW_QUEUE_FULL",
                    message="현재 검토 요청을 받을 수 없습니다.",
                    retry_after_seconds=self.policy.retry_after_seconds,
                )
            with self.database.session() as session:
                queued = SqlAlchemyReviewRepository(session).count_queued()
            if queued >= self.policy.queue_capacity:
                raise OverCapacityError(
                    code="REVIEW_QUEUE_FULL",
                    message="현재 검토 요청이 많습니다. 잠시 후 다시 시도해 주세요.",
                    retry_after_seconds=self.policy.retry_after_seconds,
                )
            yield

    async def enqueue(self, review_id: str) -> bool:
        """commit된 QUEUED ID를 중복 없이 런타임 mirror에 추가한다."""
        async with self._condition:
            if review_id in self._pending_set or review_id == self.current_review_id:
                return False
            if len(self._pending) >= self.policy.queue_capacity:
                raise RuntimeError("검토 런타임 큐와 DB 원장이 불일치합니다.")
            self._pending.append(review_id)
            self._pending_set.add(review_id)
            self._condition.notify()
            return True

    async def remove(self, review_id: str) -> None:
        """대기 작업을 제거하거나 현재 실행 작업을 취소한다."""
        task = None
        async with self._condition:
            if review_id in self._pending_set:
                self._pending.remove(review_id)
                self._pending_set.remove(review_id)
                self._condition.notify_all()
            if review_id == self.current_review_id:
                task = self.current_execution_task
                if task is not None:
                    task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def reconcile(self) -> int:
        """DB의 오래된 QUEUED 최대 용량을 FIFO로 복원한다."""
        with self.database.session() as session:
            queued = SqlAlchemyReviewRepository(session).list_queued()
        for review in queued[: self.policy.queue_capacity]:
            await self.enqueue(review.id)
        return len(queued)

    async def start(self) -> None:
        if self.worker_task is not None:
            raise RuntimeError("ReviewScheduler는 한 번만 시작할 수 있습니다.")
        self.worker_task = asyncio.create_task(self._run(), name="review-scheduler")

    async def stop(self) -> None:
        self._accepting = False
        worker = self.worker_task
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        self.worker_task = None

    async def _next(self) -> str:
        async with self._condition:
            await self._condition.wait_for(lambda: bool(self._pending))
            review_id = self._pending.popleft()
            self._pending_set.remove(review_id)
            return review_id

    async def _run(self) -> None:
        while True:
            review_id = await self._next()
            with self.database.session() as session:
                review = SqlAlchemyReviewRepository(session).get(review_id)
            if review is None or review.state is not ReviewState.QUEUED:
                continue
            self.current_review_id = review_id
            execution = asyncio.create_task(self._executor(review_id))
            self.current_execution_task = execution
            try:
                await execution
            except asyncio.CancelledError:
                worker_is_stopping = asyncio.current_task().cancelling() > 0
                if worker_is_stopping and not execution.done():
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                if worker_is_stopping:
                    raise
            except Exception:
                log_event(
                    event="review.scheduler.execution_failed",
                    request_id="system",
                    state="failed",
                    error_type="unexpected",
                    level=logging.ERROR,
                )
            finally:
                self.current_execution_task = None
                self.current_review_id = None
