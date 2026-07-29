"""검토 세션 기능 정책의 기본값과 불변 조건을 검증한다."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.domains.review_sessions.policy import (
    DEFAULT_REVIEW_SESSION_POLICY,
    ReviewSessionPolicy,
)


def test_default_review_session_policy_matches_product_policy() -> None:
    assert DEFAULT_REVIEW_SESSION_POLICY == ReviewSessionPolicy(
        max_upload_size_bytes=10 * 1024 * 1024,
        supported_file_extensions=("hwp", "hwpx", "pdf", "docx"),
        temp_upload_dir=Path("data/99_uploads"),
        session_ttl_seconds=30 * 60,
    )


def test_review_session_policy_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        DEFAULT_REVIEW_SESSION_POLICY.session_ttl_seconds = 10


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_upload_size_bytes": 0},
        {"supported_file_extensions": ()},
        {"supported_file_extensions": ("pdf", "xlsx")},
        {"session_ttl_seconds": 0},
    ],
)
def test_review_session_policy_rejects_invalid_values(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        ReviewSessionPolicy(**overrides)
