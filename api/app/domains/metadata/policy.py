"""프론트 초기화 메타데이터에 적용하는 고정 캐시 정책."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetadataPolicy:
    """메타데이터 응답과 서버 캐시의 TTL 정책."""

    cache_ttl_seconds: int = 5 * 60

    def __post_init__(self) -> None:
        if self.cache_ttl_seconds <= 0:
            raise ValueError("메타데이터 캐시 TTL은 양수여야 합니다.")


DEFAULT_METADATA_POLICY = MetadataPolicy()
"""운영과 일반 요청에 적용하는 기본 메타데이터 캐시 정책."""
