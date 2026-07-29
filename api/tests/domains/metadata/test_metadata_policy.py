"""메타데이터 캐시 정책의 기본값과 불변 조건을 검증한다."""

import pytest

from app.domains.metadata.policy import DEFAULT_METADATA_POLICY, MetadataPolicy


def test_default_metadata_policy_matches_http_cache_policy() -> None:
    assert DEFAULT_METADATA_POLICY == MetadataPolicy(cache_ttl_seconds=5 * 60)


def test_metadata_policy_rejects_non_positive_ttl() -> None:
    with pytest.raises(ValueError):
        MetadataPolicy(cache_ttl_seconds=0)
