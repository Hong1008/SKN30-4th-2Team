"""작업 유형별 고정 admission 정책."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QueuedAdmissionPolicy:
    """실행 슬롯과 제한된 FIFO 대기열 정책."""

    concurrency: int
    queue_capacity: int
    retry_after_seconds: int
    wait_seconds: float | None = None

    def __post_init__(self) -> None:
        if min(
            self.concurrency,
            self.queue_capacity,
            self.retry_after_seconds,
        ) <= 0:
            raise ValueError("admission policy 값은 양수여야 합니다.")
        if self.wait_seconds is not None and self.wait_seconds <= 0:
            raise ValueError("queue wait 시간은 양수여야 합니다.")


@dataclass(frozen=True, slots=True)
class ImmediateAdmissionPolicy:
    """대기 없이 실행 슬롯만 허용하는 정책."""

    concurrency: int
    retry_after_seconds: int

    def __post_init__(self) -> None:
        if self.concurrency <= 0 or self.retry_after_seconds <= 0:
            raise ValueError("admission policy 값은 양수여야 합니다.")


REVIEW_POLICY = QueuedAdmissionPolicy(
    concurrency=1,
    queue_capacity=5,
    retry_after_seconds=30,
)
SUGGESTION_POLICY = QueuedAdmissionPolicy(
    concurrency=1,
    queue_capacity=5,
    retry_after_seconds=20,
    wait_seconds=60,
)
UPLOAD_POLICY = ImmediateAdmissionPolicy(
    concurrency=2,
    retry_after_seconds=5,
)
