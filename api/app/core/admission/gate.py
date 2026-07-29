"""취소 안전한 FIFO gate와 즉시 동시성 제한기."""

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from app.core.admission.policy import (
    ImmediateAdmissionPolicy,
    QueuedAdmissionPolicy,
)
from app.core.common.errors import OverCapacityError


class BoundedFifoGate:
    """실행 수와 FIFO 대기자 수를 함께 제한한다."""

    def __init__(
        self,
        policy: QueuedAdmissionPolicy,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        self.policy = policy
        self._error_code = error_code
        self._error_message = error_message
        self._condition = asyncio.Condition()
        self._waiters: deque[object] = deque()
        self._active = 0

    @property
    def active(self) -> int:
        return self._active

    @property
    def waiting(self) -> int:
        return len(self._waiters)

    def _capacity_error(self) -> OverCapacityError:
        return OverCapacityError(
            code=self._error_code,
            message=self._error_message,
            retry_after_seconds=self.policy.retry_after_seconds,
        )

    async def _acquire(self) -> None:
        token = object()
        async with self._condition:
            if self._active < self.policy.concurrency and not self._waiters:
                self._active += 1
                return
            if len(self._waiters) >= self.policy.queue_capacity:
                raise self._capacity_error()
            self._waiters.append(token)
            try:
                waiter = self._condition.wait_for(
                    lambda: (
                        self._waiters
                        and self._waiters[0] is token
                        and self._active < self.policy.concurrency
                    )
                )
                if self.policy.wait_seconds is None:
                    await waiter
                else:
                    await asyncio.wait_for(waiter, self.policy.wait_seconds)
                self._waiters.popleft()
                self._active += 1
            except asyncio.CancelledError:
                if token in self._waiters:
                    self._waiters.remove(token)
                self._condition.notify_all()
                raise
            except TimeoutError:
                if token in self._waiters:
                    self._waiters.remove(token)
                self._condition.notify_all()
                raise self._capacity_error()

    async def _release(self) -> None:
        async with self._condition:
            self._active -= 1
            self._condition.notify_all()

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """슬롯을 얻고 모든 종료 경로에서 반환한다."""
        await self._acquire()
        try:
            yield
        finally:
            await self._release()


class ImmediateConcurrencyLimiter:
    """빈 슬롯이 없으면 기다리지 않고 즉시 거부한다."""

    def __init__(
        self,
        policy: ImmediateAdmissionPolicy,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        self.policy = policy
        self._error_code = error_code
        self._error_message = error_message
        self._lock = asyncio.Lock()
        self._active = 0

    @property
    def active(self) -> int:
        return self._active

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        async with self._lock:
            if self._active >= self.policy.concurrency:
                raise OverCapacityError(
                    code=self._error_code,
                    message=self._error_message,
                    retry_after_seconds=self.policy.retry_after_seconds,
                )
            self._active += 1
        try:
            yield
        finally:
            async with self._lock:
                self._active -= 1
