"""휘발성 파일과 만료 데이터 정리에 적용하는 고정 기능 정책."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoragePolicy:
    """주기적 정리와 만료 tombstone 보존 정책."""

    cleanup_interval_seconds: int = 60
    expired_tombstone_ttl_seconds: int = 24 * 60 * 60

    def __post_init__(self) -> None:
        if self.cleanup_interval_seconds <= 0:
            raise ValueError("스토리지 정리 주기는 양수여야 합니다.")
        if self.expired_tombstone_ttl_seconds <= 0:
            raise ValueError("만료 tombstone TTL은 양수여야 합니다.")


DEFAULT_STORAGE_POLICY = StoragePolicy()
"""운영과 일반 요청에 적용하는 기본 스토리지 정리 정책."""
