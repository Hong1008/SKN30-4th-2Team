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


def test_grounding_log_contains_category_status_and_sources(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    log_event(
        event="mcp.grounding.completed",
        request_id="req_test",
        review_id="rev_test",
        category="LIABILITY",
        state="OK",
        sources=["law_1", "law_2"],
    )

    assert "event=mcp.grounding.completed" in caplog.text
    assert "category=LIABILITY" in caplog.text
    assert "state=OK" in caplog.text
    assert "sources=law_1,law_2" in caplog.text


def test_failure_log_contains_exception_type_without_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="uvicorn.error")

    log_event(
        event="llm.suggestion.invalid_output",
        review_id="rev_test",
        state="LLM_OUTPUT_INVALID",
        error_type="ValidationError",
        level=logging.ERROR,
    )

    assert "error_type=ValidationError" in caplog.text
    assert "event=llm.suggestion.invalid_output" in caplog.text
