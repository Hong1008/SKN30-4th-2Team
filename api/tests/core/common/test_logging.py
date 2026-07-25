"""허용된 비식별 필드만 기록하는 공통 이벤트 로그를 검증한다."""

import logging

import pytest

from app.core.common.logging import hash_session_id, log_event


def test_session_id_is_hashed_before_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_session_id = "ses-secret-value"
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    log_event(
        event="review.started",
        request_id="req_test",
        session_id=raw_session_id,
        review_id="rev_test",
        state="RUNNING",
        duration_ms=12.34,
    )

    assert raw_session_id not in caplog.text
    assert f"session_id_hash={hash_session_id(raw_session_id)}" in caplog.text
    assert "event=review.started" in caplog.text
    assert "request_id=req_test" in caplog.text
    assert "review_id=rev_test" in caplog.text
    assert "state=RUNNING" in caplog.text
    assert "duration_ms=12.34" in caplog.text
