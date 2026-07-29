"""계약서 업로드와 검토 세션에 적용하는 고정 기능 정책."""

from dataclasses import dataclass
from pathlib import Path


PRODUCT_SUPPORTED_FILE_EXTENSIONS = ("hwp", "hwpx", "pdf", "docx")
"""제품이 지원하는 계약서 파일 확장자."""


@dataclass(frozen=True, slots=True)
class ReviewSessionPolicy:
    """업로드 입력과 익명 검토 세션의 수명 정책."""

    max_upload_size_bytes: int = 10 * 1024 * 1024
    supported_file_extensions: tuple[str, ...] = (
        PRODUCT_SUPPORTED_FILE_EXTENSIONS
    )
    temp_upload_dir: Path = Path("data/99_uploads")
    session_ttl_seconds: int = 30 * 60

    def __post_init__(self) -> None:
        if self.max_upload_size_bytes <= 0:
            raise ValueError("최대 업로드 크기는 양수여야 합니다.")
        if not self.supported_file_extensions:
            raise ValueError("지원 파일 확장자는 비어 있을 수 없습니다.")
        unsupported = set(self.supported_file_extensions) - set(
            PRODUCT_SUPPORTED_FILE_EXTENSIONS
        )
        if unsupported:
            raise ValueError("제품 지원 범위 밖의 파일 확장자는 허용할 수 없습니다.")
        if self.session_ttl_seconds <= 0:
            raise ValueError("검토 세션 TTL은 양수여야 합니다.")


DEFAULT_REVIEW_SESSION_POLICY = ReviewSessionPolicy()
"""운영과 일반 요청에 적용하는 기본 검토 세션 정책."""
