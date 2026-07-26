"""멱등 응답 저장 경쟁 처리 검증."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.idempotency.service import (
    find_replay,
    idempotency_guard,
    request_fingerprint,
    save_response,
)
from app.domains.review_sessions.domain import ReviewSession, ReviewSessionState
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.domains.reviews.domain import Review
from app.domains.reviews.repository import SqlAlchemyReviewRepository


def test_save_response_recovers_winning_snapshot_after_unique_race(database) -> None:
    session_id = "ses_idempotency_race"
    now = datetime.now(UTC)
    with database.session() as setup_session:
        SqlAlchemyReviewSessionRepository(setup_session).add(
            ReviewSession(
                id=session_id,
                access_token_hash="hash",
                state=ReviewSessionState.TYPE_SELECTION_REQUIRED,
                original_file_name="contract.pdf",
                file_size_bytes=1,
                storage_key="storage-key.pdf",
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        setup_session.commit()

    fingerprint = request_fingerprint({"review_id": "rev_1", "message": "질문"})
    with database.session() as stale_request, database.session() as winner:
        assert (
            find_replay(
                stale_request,
                scope="reviews.chat",
                session_id=session_id,
                idempotency_key="same-key",
                fingerprint=fingerprint,
            )
            is None
        )

        assert (
            save_response(
                winner,
                scope="reviews.chat",
                session_id=session_id,
                idempotency_key="same-key",
                fingerprint=fingerprint,
                response_snapshot={"answer": "winner"},
                ttl_seconds=3600,
            )
            is None
        )
        winner.commit()

        replay = save_response(
            stale_request,
            scope="reviews.chat",
            session_id=session_id,
            idempotency_key="same-key",
            fingerprint=fingerprint,
            response_snapshot={"answer": "stale"},
            ttl_seconds=3600,
        )

    assert replay == {"answer": "winner"}


def test_review_and_response_transaction_loses_race_as_one_unit(database) -> None:
    session_id = "ses_review_race"
    operation_key = "op_same-review"
    now = datetime.now(UTC)
    with database.session() as setup_session:
        SqlAlchemyReviewSessionRepository(setup_session).add(
            ReviewSession(
                id=session_id,
                access_token_hash="hash",
                state=ReviewSessionState.READY_TO_REVIEW,
                original_file_name="contract.pdf",
                file_size_bytes=1,
                storage_key="storage-key.pdf",
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(hours=1),
                selected_contract_type="SW_FREELANCE",
            )
        )
        setup_session.commit()

    fingerprint = request_fingerprint({"session_id": session_id})
    with database.session() as stale_request, database.session() as winner:
        SqlAlchemyReviewRepository(stale_request).add(
            Review.queued(
                review_id="rev_stale",
                session_id=session_id,
                idempotency_key=operation_key,
                contract_type="SW_FREELANCE",
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        SqlAlchemyReviewRepository(winner).add(
            Review.queued(
                review_id="rev_winner",
                session_id=session_id,
                idempotency_key=operation_key,
                contract_type="SW_FREELANCE",
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        save_response(
            winner,
            scope="reviews.create",
            session_id=session_id,
            idempotency_key="same-key",
            fingerprint=fingerprint,
            response_snapshot={"review_id": "rev_winner"},
            ttl_seconds=3600,
        )
        winner.commit()

        replay = save_response(
            stale_request,
            scope="reviews.create",
            session_id=session_id,
            idempotency_key="same-key",
            fingerprint=fingerprint,
            response_snapshot={"review_id": "rev_stale"},
            ttl_seconds=3600,
        )

    assert replay == {"review_id": "rev_winner"}
    with database.session() as check_session:
        repository = SqlAlchemyReviewRepository(check_session)
        assert repository.get("rev_winner") is not None
        assert repository.get("rev_stale") is None


@pytest.mark.asyncio
async def test_idempotency_guard_serializes_same_process_external_work() -> None:
    snapshot: dict[str, str] | None = None
    external_calls = 0

    async def execute() -> dict[str, str]:
        nonlocal external_calls, snapshot
        async with idempotency_guard(
            scope="reviews.chat",
            session_id="ses_guard",
            idempotency_key="same-key",
        ):
            if snapshot is not None:
                return snapshot
            external_calls += 1
            await asyncio.sleep(0)
            snapshot = {"answer": "generated"}
            return snapshot

    first, second = await asyncio.gather(execute(), execute())

    assert first == second == {"answer": "generated"}
    assert external_calls == 1
