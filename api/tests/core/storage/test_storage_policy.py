"""파일 정리 정책의 기본값과 불변 조건을 검증한다."""

import pytest

from app.core.storage.policy import DEFAULT_STORAGE_POLICY, StoragePolicy


def test_default_storage_policy_matches_cleanup_policy() -> None:
    assert DEFAULT_STORAGE_POLICY == StoragePolicy(
        cleanup_interval_seconds=60,
        expired_tombstone_ttl_seconds=24 * 60 * 60,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"cleanup_interval_seconds": 0},
        {"expired_tombstone_ttl_seconds": 0},
    ],
)
def test_storage_policy_rejects_invalid_values(
    overrides: dict[str, int],
) -> None:
    with pytest.raises(ValueError):
        StoragePolicy(**overrides)
