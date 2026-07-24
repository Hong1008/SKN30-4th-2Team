"""HTTP 계층에 의존하지 않는 애플리케이션 공통 오류를 정의한다."""

from collections.abc import Mapping
from typing import Any


class AppError(Exception):
    """사용자에게 안전하게 변환할 수 있는 애플리케이션 오류."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        field: str | None = None,
        retryable: bool = False,
        next_action: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.retryable = retryable
        self.next_action = next_action
        self.details = dict(details or {})


class AppValidationError(AppError):
    """형식은 유효하지만 애플리케이션 입력 규칙을 만족하지 못한 오류."""


class NotFoundError(AppError):
    """리소스가 없거나 요청 주체가 접근할 수 없는 오류."""


class ConflictError(AppError):
    """현재 상태와 요청한 동작이 충돌하는 오류."""


class ExpiredError(AppError):
    """세션 또는 임시 결과의 사용 기한이 지난 오류."""


class ExternalServiceError(AppError):
    """MCP 또는 LLM 등 외부 서비스 처리 오류."""


class ExternalServiceTimeoutError(ExternalServiceError):
    """외부 서비스가 제한 시간 안에 응답하지 않은 오류."""
