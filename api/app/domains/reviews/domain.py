"""검토 작업의 순수 도메인 타입과 Aggregate."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import math
from typing import Any, Mapping


class ReviewState(StrEnum):
    """애플리케이션 검토 작업 상태."""

    QUEUED = "QUEUED"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class MCPReviewStatus(StrEnum):
    """MCP 전체 검토 응답의 원본 상태."""

    OK = "OK"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    CORPUS_UNAVAILABLE = "CORPUS_UNAVAILABLE"
    INVALID_CONFIG = "INVALID_CONFIG"
    PIPELINE_ERROR = "PIPELINE_ERROR"


class ProgressStage(StrEnum):
    """화면에 노출하는 검토 진행 단계."""

    PREPARE = "PREPARE"
    BATCH_SEARCH = "BATCH_SEARCH"
    RERANK = "RERANK"
    CLAUSE_REVIEW = "CLAUSE_REVIEW"
    MISSING_DETECTION = "MISSING_DETECTION"
    RESULT_ASSEMBLY = "RESULT_ASSEMBLY"


_STAGE_ORDER = {stage: index for index, stage in enumerate(ProgressStage)}
_MAX_PROGRESS_MESSAGE_LENGTH = 300


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    """외부에서 수정할 수 없는 단일 progress 스냅샷."""

    sequence: int
    stage: ProgressStage
    current: float
    total: float | None
    percent: int
    message: str | None

    def to_dict(self) -> dict[str, Any]:
        """기존 API JSON 형태로 변환한다."""
        return {
            "sequence": self.sequence,
            "stage": self.stage.value,
            "current": self.current,
            "total": self.total,
            "percent": self.percent,
            "message": self.message,
        }

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
    ) -> "ProgressSnapshot | None":
        """DB의 이전 progress JSON을 안전한 값 객체로 복원한다."""
        if value is None:
            return None
        try:
            stage = ProgressStage(str(value.get("stage", "PREPARE")).upper())
        except ValueError:
            stage = ProgressStage.PREPARE
        return cls(
            sequence=int(value.get("sequence", 0)),
            stage=stage,
            current=float(value.get("current", 0)),
            total=(
                float(value["total"])
                if value.get("total") is not None
                else None
            ),
            percent=int(value.get("percent", 0)),
            message=_safe_message(value.get("message")),
        )


def _safe_message(value: object) -> str | None:
    if value is None:
        return None
    text = "".join(
        character for character in str(value) if character.isprintable()
    )
    return text[:_MAX_PROGRESS_MESSAGE_LENGTH]


class Review:
    """한 번의 MCP 전체 검토와 결과 스냅샷을 관리하는 Aggregate Root."""

    __slots__ = (
        "id",
        "session_id",
        "idempotency_key",
        "contract_type",
        "created_at",
        "expires_at",
        "retry_of_review_id",
        "mcp_review_status",
        "result",
        "error",
        "started_at",
        "completed_at",
        "version",
        "_state",
        "_progress",
    )

    def __init__(
        self,
        *,
        review_id: str,
        session_id: str,
        idempotency_key: str,
        contract_type: str,
        created_at: datetime,
        expires_at: datetime,
        state: ReviewState,
        retry_of_review_id: str | None = None,
        mcp_review_status: MCPReviewStatus | None = None,
        progress: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
        error: Mapping[str, Any] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        version: int = 0,
    ) -> None:
        self.id = review_id
        self.session_id = session_id
        self.idempotency_key = idempotency_key
        self.contract_type = contract_type
        self.created_at = created_at
        self.expires_at = expires_at
        self.retry_of_review_id = retry_of_review_id
        self.mcp_review_status = mcp_review_status
        self.result = deepcopy(dict(result)) if result is not None else None
        self.error = deepcopy(dict(error)) if error is not None else None
        self.started_at = started_at
        self.completed_at = completed_at
        self.version = version
        self._state = state
        self._progress = ProgressSnapshot.from_mapping(progress)

    @classmethod
    def queued(
        cls,
        *,
        review_id: str,
        session_id: str,
        idempotency_key: str,
        contract_type: str,
        created_at: datetime,
        expires_at: datetime,
        retry_of_review_id: str | None = None,
    ) -> "Review":
        """새 QUEUED 검토를 생성한다."""
        return cls(
            review_id=review_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
            contract_type=contract_type,
            created_at=created_at,
            expires_at=expires_at,
            retry_of_review_id=retry_of_review_id,
            state=ReviewState.QUEUED,
            progress={
                "sequence": 0,
                "stage": ProgressStage.PREPARE.value,
                "current": 0,
                "total": None,
                "percent": 0,
                "message": "검토를 준비하고 있습니다.",
            },
        )

    @classmethod
    def restore(cls, **values: Any) -> "Review":
        """신뢰한 영속 스냅샷으로 Aggregate를 복원한다."""
        return cls(**values)

    @property
    def state(self) -> ReviewState:
        return self._state

    @property
    def progress(self) -> dict[str, Any] | None:
        """외부 변경이 내부 상태에 반영되지 않는 progress 복사본."""
        return self._progress.to_dict() if self._progress is not None else None

    def start(self, *, at: datetime) -> None:
        """QUEUED 검토를 실행 중으로 전환한다."""
        self._require_state(ReviewState.QUEUED)
        self._state = ReviewState.REVIEWING
        self.started_at = at
        self.completed_at = None
        self.result = None
        self.error = None
        self.mcp_review_status = None
        self._progress = ProgressSnapshot(
            sequence=(self._progress.sequence if self._progress else 0) + 1,
            stage=ProgressStage.PREPARE,
            current=0,
            total=None,
            percent=0,
            message="검토를 준비하고 있습니다.",
        )

    def record_progress(
        self,
        *,
        stage: str,
        current: float,
        total: float | None,
        message: str | None,
    ) -> bool:
        """REVIEWING progress를 단조 규칙에 따라 기록한다."""
        self._require_state(ReviewState.REVIEWING)
        previous = self._progress
        if previous is None:
            raise ValueError("REVIEWING 상태에는 progress가 필요합니다.")
        try:
            requested_stage = ProgressStage(stage.upper())
        except ValueError:
            self._progress = ProgressSnapshot(
                sequence=previous.sequence + 1,
                stage=previous.stage,
                current=previous.current,
                total=previous.total,
                percent=previous.percent,
                message=_safe_message(message),
            )
            return True
        previous_order = _STAGE_ORDER[previous.stage]
        requested_order = _STAGE_ORDER[requested_stage]
        if requested_order < previous_order:
            return False

        forward = requested_order > previous_order
        normalized_current = float(current)
        if not math.isfinite(normalized_current):
            normalized_current = previous.current
        normalized_current = max(0.0, normalized_current)
        normalized_total = (
            float(total) if total is not None else None
        )
        if normalized_total is not None and not math.isfinite(normalized_total):
            normalized_total = previous.total
        if normalized_total is not None:
            normalized_total = max(0.0, normalized_total)
        if not forward:
            normalized_current = max(previous.current, normalized_current)
            normalized_total = previous.total
        if normalized_total and normalized_total > 0:
            calculated_percent = math.floor(
                normalized_current / normalized_total * 100
            )
        else:
            calculated_percent = math.floor(normalized_current)
        percent = max(previous.percent, min(calculated_percent, 99))
        self._progress = ProgressSnapshot(
            sequence=previous.sequence + 1,
            stage=requested_stage,
            current=normalized_current,
            total=normalized_total,
            percent=percent,
            message=_safe_message(message),
        )
        return True

    def complete(
        self,
        mcp_status: MCPReviewStatus,
        result: Mapping[str, Any],
        *,
        at: datetime,
    ) -> None:
        """MCP OK 결과만 COMPLETED로 확정한다."""
        self._require_state(ReviewState.REVIEWING)
        if mcp_status is not MCPReviewStatus.OK:
            raise ValueError("COMPLETED 전이에는 MCP OK 상태가 필요합니다.")
        sequence = self._progress.sequence if self._progress else 0
        self._state = ReviewState.COMPLETED
        self.mcp_review_status = mcp_status
        self.result = deepcopy(dict(result))
        self.error = None
        self.completed_at = at
        self._progress = ProgressSnapshot(
            sequence=sequence + 1,
            stage=ProgressStage.RESULT_ASSEMBLY,
            current=1,
            total=1,
            percent=100,
            message="검토 결과 정리가 완료되었습니다.",
        )

    def fail(
        self,
        error: Mapping[str, Any],
        mcp_status: MCPReviewStatus | None = None,
        *,
        at: datetime,
    ) -> None:
        """활성 검토를 성공으로 오인되지 않는 FAILED로 전환한다."""
        if self._state not in {ReviewState.QUEUED, ReviewState.REVIEWING}:
            self._invalid_transition(ReviewState.FAILED)
        self._state = ReviewState.FAILED
        self.mcp_review_status = mcp_status
        self.result = None
        self.error = deepcopy(dict(error))
        self.completed_at = at

    def mark_interrupted(self, *, at: datetime) -> None:
        """서버 재시작으로 중단된 활성 검토를 retryable 실패로 전환한다."""
        self.fail(
            {
                "code": "REVIEW_INTERRUPTED",
                "retryable": True,
                "next_action": "RETRY_REVIEW",
            },
            at=at,
        )

    def cancel(self, *, at: datetime) -> None:
        """검토와 민감 결과를 폐기한다. 반복 취소는 멱등이다."""
        if self._state is ReviewState.CANCELLED:
            return
        if self._state is ReviewState.EXPIRED:
            self._invalid_transition(ReviewState.CANCELLED)
        previous = self._progress
        self._state = ReviewState.CANCELLED
        self.result = None
        self.error = None
        self._progress = ProgressSnapshot(
            sequence=(previous.sequence if previous else 0) + 1,
            stage=previous.stage if previous else ProgressStage.PREPARE,
            current=previous.current if previous else 0,
            total=previous.total if previous else None,
            percent=previous.percent if previous else 0,
            message=None,
        )
        self.completed_at = at

    def expire(self, *, at: datetime) -> None:
        """terminal 검토의 민감 스냅샷을 폐기하고 EXPIRED로 전환한다."""
        if self._state not in {
            ReviewState.COMPLETED,
            ReviewState.FAILED,
            ReviewState.CANCELLED,
        }:
            self._invalid_transition(ReviewState.EXPIRED)
        self._state = ReviewState.EXPIRED
        self.result = None
        self.error = None
        self._progress = None
        self.expires_at = at

    def is_expired(self, now: datetime) -> bool:
        """주어진 시각을 기준으로 검토 결과 만료 여부를 반환한다."""
        return now >= self.expires_at

    def _require_state(self, expected: ReviewState) -> None:
        if self._state is not expected:
            self._invalid_transition(expected)

    def _invalid_transition(self, target: ReviewState) -> None:
        raise ValueError(
            f"허용되지 않은 Review 상태 전이입니다: {self._state} -> {target}"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Review):
            return NotImplemented
        return all(
            getattr(self, name) == getattr(other, name)
            for name in self.__slots__
        )
