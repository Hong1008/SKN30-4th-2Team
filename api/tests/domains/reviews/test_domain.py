"""Review Aggregate의 상태 전이와 진행률 불변식을 검증한다."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domains.reviews.domain import (
    MCPReviewStatus,
    Review,
    ReviewState,
)


def queued_review() -> Review:
    now = datetime.now(UTC)
    return Review.queued(
        review_id="rev_domain",
        session_id="ses_domain",
        idempotency_key="idem-domain",
        contract_type="SW_FREELANCE",
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )


def test_state_and_progress_are_read_only() -> None:
    review = queued_review()

    with pytest.raises(AttributeError):
        review.state = ReviewState.REVIEWING  # type: ignore[misc]
    with pytest.raises(AttributeError):
        review.progress = {"sequence": 99}  # type: ignore[misc]


def test_happy_path_completes_only_with_mcp_ok() -> None:
    review = queued_review()
    started_at = datetime.now(UTC)
    completed_at = started_at + timedelta(seconds=1)

    review.start(at=started_at)
    review.complete(
        MCPReviewStatus.OK,
        {"clause_results": [], "missing_standard_clauses": []},
        at=completed_at,
    )

    assert review.state is ReviewState.COMPLETED
    assert review.result == {
        "clause_results": [],
        "missing_standard_clauses": [],
    }
    assert review.progress == {
        "sequence": 2,
        "stage": "RESULT_ASSEMBLY",
        "current": 1,
        "total": 1,
        "percent": 100,
        "message": "검토 결과 정리가 완료되었습니다.",
    }
    with pytest.raises(ValueError):
        review.start(at=completed_at)


def test_complete_rejects_non_ok_mcp_status() -> None:
    review = queued_review()
    review.start(at=datetime.now(UTC))

    with pytest.raises(ValueError):
        review.complete(
            MCPReviewStatus.PIPELINE_ERROR,
            {},
            at=datetime.now(UTC),
        )


@pytest.mark.parametrize("initial_state", [ReviewState.QUEUED, ReviewState.REVIEWING])
def test_fail_is_allowed_only_from_active_states(initial_state: ReviewState) -> None:
    review = queued_review()
    if initial_state is ReviewState.REVIEWING:
        review.start(at=datetime.now(UTC))

    review.fail(
        {
            "code": "PIPELINE_ERROR",
            "retryable": True,
            "next_action": "RETRY_REVIEW",
        },
        MCPReviewStatus.PIPELINE_ERROR,
        at=datetime.now(UTC),
    )

    assert review.state is ReviewState.FAILED
    assert review.progress is not None
    assert review.progress["percent"] < 100


def test_cancel_is_idempotent_and_expired_rejects_every_transition() -> None:
    review = queued_review()
    now = datetime.now(UTC)
    review.cancel(at=now)
    review.cancel(at=now)

    assert review.state is ReviewState.CANCELLED
    assert review.result is None
    assert review.progress == {
        "sequence": 1,
        "stage": "PREPARE",
        "current": 0,
        "total": None,
        "percent": 0,
        "message": None,
    }
    assert review.error is None

    review.expire(at=now)
    assert review.state is ReviewState.EXPIRED
    for transition in (
        lambda: review.start(at=now),
        lambda: review.fail({"code": "x"}, at=now),
        lambda: review.cancel(at=now),
        lambda: review.expire(at=now),
    ):
        with pytest.raises(ValueError):
            transition()


def test_progress_is_monotonic_and_ignores_late_stage() -> None:
    review = queued_review()
    review.start(at=datetime.now(UTC))

    assert review.record_progress(
        stage="CLAUSE_REVIEW",
        current=7,
        total=10,
        message="분류 중",
    )
    assert review.record_progress(
        stage="CLAUSE_REVIEW",
        current=3,
        total=10,
        message="늦은 같은 단계 이벤트",
    )
    before_late = review.progress
    assert not review.record_progress(
        stage="RERANK",
        current=9,
        total=10,
        message="늦은 이전 단계 이벤트",
    )

    assert review.progress == before_late
    assert review.progress == {
        "sequence": 3,
        "stage": "CLAUSE_REVIEW",
        "current": 7,
        "total": 10,
        "percent": 70,
        "message": "늦은 같은 단계 이벤트",
    }


def test_forward_stage_may_reset_counts_but_not_percent() -> None:
    review = queued_review()
    review.start(at=datetime.now(UTC))
    review.record_progress(
        stage="CLAUSE_REVIEW",
        current=9,
        total=10,
        message="분류 중",
    )
    review.record_progress(
        stage="MISSING_DETECTION",
        current=0,
        total=2,
        message="누락 탐지",
    )

    assert review.progress is not None
    assert review.progress["sequence"] == 3
    assert review.progress["current"] == 0
    assert review.progress["total"] == 2
    assert review.progress["percent"] == 90


def test_unknown_stage_keeps_stage_and_bounds_message() -> None:
    review = queued_review()
    review.start(at=datetime.now(UTC))

    review.record_progress(
        stage="FUTURE_STAGE",
        current=99,
        total=100,
        message="x" * 1000,
    )

    assert review.progress is not None
    assert review.progress["stage"] == "PREPARE"
    assert review.progress["sequence"] == 2
    assert review.progress["current"] == 0
    assert review.progress["total"] is None
    assert review.progress["percent"] == 0
    assert len(review.progress["message"]) <= 300


@pytest.mark.parametrize(
    "state",
    [
        ReviewState.QUEUED,
        ReviewState.REVIEWING,
        ReviewState.COMPLETED,
        ReviewState.FAILED,
    ],
)
def test_cancel_is_allowed_from_every_non_expired_state(
    state: ReviewState,
) -> None:
    review = queued_review()
    now = datetime.now(UTC)
    if state is ReviewState.REVIEWING:
        review.start(at=now)
    elif state is ReviewState.COMPLETED:
        review.start(at=now)
        review.complete(MCPReviewStatus.OK, {}, at=now)
    elif state is ReviewState.FAILED:
        review.fail({"code": "failure"}, at=now)

    review.cancel(at=now)
    review.cancel(at=now)

    assert review.state is ReviewState.CANCELLED


def test_cancel_preserves_last_progress_numbers_and_advances_sequence() -> None:
    review = queued_review()
    now = datetime.now(UTC)
    review.start(at=now)
    review.record_progress(
        stage="CLAUSE_REVIEW",
        current=7,
        total=10,
        message="분류 중",
    )

    review.cancel(at=now)

    assert review.progress == {
        "sequence": 3,
        "stage": "CLAUSE_REVIEW",
        "current": 7,
        "total": 10,
        "percent": 70,
        "message": None,
    }


@pytest.mark.parametrize(
    "state",
    [ReviewState.COMPLETED, ReviewState.FAILED, ReviewState.CANCELLED],
)
def test_expire_is_allowed_only_from_terminal_states(state: ReviewState) -> None:
    review = queued_review()
    now = datetime.now(UTC)
    if state is ReviewState.COMPLETED:
        review.start(at=now)
        review.complete(MCPReviewStatus.OK, {}, at=now)
    elif state is ReviewState.FAILED:
        review.fail({"code": "failure"}, at=now)
    else:
        review.cancel(at=now)

    review.expire(at=now)

    assert review.state is ReviewState.EXPIRED


def test_expired_rejects_all_domain_operations() -> None:
    review = queued_review()
    now = datetime.now(UTC)
    review.cancel(at=now)
    review.expire(at=now)

    operations = (
        lambda: review.start(at=now),
        lambda: review.complete(MCPReviewStatus.OK, {}, at=now),
        lambda: review.fail({"code": "failure"}, at=now),
        lambda: review.mark_interrupted(at=now),
        lambda: review.cancel(at=now),
        lambda: review.expire(at=now),
        lambda: review.record_progress(
            stage="PREPARE",
            current=0,
            total=None,
            message="late",
        ),
    )
    for operation in operations:
        with pytest.raises(ValueError):
            operation()
