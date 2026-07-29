"""공통 admission gate의 상한·FIFO·취소 반환을 검증한다."""

import asyncio

import pytest

from app.core.admission.gate import BoundedFifoGate, ImmediateConcurrencyLimiter
from app.core.admission.policy import ImmediateAdmissionPolicy, QueuedAdmissionPolicy
from app.core.common.errors import OverCapacityError


pytestmark = pytest.mark.asyncio


async def test_immediate_limiter_rejects_over_capacity_and_releases() -> None:
    limiter = ImmediateConcurrencyLimiter(
        ImmediateAdmissionPolicy(concurrency=2, retry_after_seconds=5),
        error_code="UPLOAD_CAPACITY_EXCEEDED",
        error_message="busy",
    )

    async with limiter.slot(), limiter.slot():
        with pytest.raises(OverCapacityError) as captured:
            async with limiter.slot():
                pass
        assert captured.value.retry_after_seconds == 5

    async with limiter.slot():
        assert limiter.active == 1


async def test_fifo_gate_limits_waiters_and_preserves_order() -> None:
    gate = BoundedFifoGate(
        QueuedAdmissionPolicy(
            concurrency=1,
            queue_capacity=2,
            retry_after_seconds=20,
            wait_seconds=1,
        ),
        error_code="SUGGESTION_QUEUE_FULL",
        error_message="busy",
    )
    release = asyncio.Event()
    entered: list[int] = []

    async def work(number: int) -> None:
        async with gate.slot():
            entered.append(number)
            if number == 0:
                await release.wait()

    active = asyncio.create_task(work(0))
    await asyncio.sleep(0)
    first = asyncio.create_task(work(1))
    await asyncio.sleep(0)
    second = asyncio.create_task(work(2))
    await asyncio.sleep(0)

    with pytest.raises(OverCapacityError):
        async with gate.slot():
            pass

    release.set()
    await asyncio.gather(active, first, second)
    assert entered == [0, 1, 2]
    assert gate.active == 0
    assert gate.waiting == 0


async def test_fifo_gate_cancelled_waiter_returns_queue_place() -> None:
    gate = BoundedFifoGate(
        QueuedAdmissionPolicy(1, 1, 1, wait_seconds=1),
        error_code="FULL",
        error_message="busy",
    )
    release = asyncio.Event()

    async def active_work() -> None:
        async with gate.slot():
            await release.wait()

    active = asyncio.create_task(active_work())
    await asyncio.sleep(0)
    waiter = asyncio.create_task(gate._acquire())
    await asyncio.sleep(0)
    assert gate.waiting == 1
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert gate.waiting == 0
    release.set()
    await active
