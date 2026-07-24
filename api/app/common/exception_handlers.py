"""애플리케이션·FastAPI 오류를 공통 API 응답으로 변환한다."""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.errors import (
    AppError,
    AppValidationError,
    ConflictError,
    ExpiredError,
    ExternalServiceError,
    ExternalServiceTimeoutError,
    NotFoundError,
)
from app.common.request_id import REQUEST_ID_HEADER, get_request_id
from app.common.responses import ApiError, ApiErrorResponse, api_meta


logger = logging.getLogger(__name__)

APP_ERROR_STATUS: tuple[tuple[type[AppError], int], ...] = (
    (AppValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (ConflictError, status.HTTP_409_CONFLICT),
    (ExpiredError, status.HTTP_410_GONE),
    (ExternalServiceTimeoutError, status.HTTP_504_GATEWAY_TIMEOUT),
    (ExternalServiceError, status.HTTP_503_SERVICE_UNAVAILABLE),
)


def _status_for(error: AppError) -> int:
    """오류의 구체 타입에 대응하는 HTTP 상태 코드를 반환한다."""
    for error_type, status_code in APP_ERROR_STATUS:
        if isinstance(error, error_type):
            return status_code
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    field: str | None = None,
    retryable: bool = False,
    next_action: str | None = None,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """공통 오류 계약과 요청 ID 헤더를 갖는 JSON 응답을 만든다."""
    payload = ApiErrorResponse(
        error=ApiError(
            code=code,
            message=message,
            field=field,
            retryable=retryable,
            next_action=next_action,
            details=details or {},
        ),
        meta=api_meta(request),
    )
    request_id = get_request_id(request)
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={REQUEST_ID_HEADER: request_id},
    )


async def app_error_handler(request: Request, error: AppError) -> JSONResponse:
    """알려진 애플리케이션 오류를 안전한 공통 응답으로 변환한다."""
    return _error_response(
        request,
        status_code=_status_for(error),
        code=error.code,
        message=error.message,
        field=error.field,
        retryable=error.retryable,
        next_action=error.next_action,
        details=error.details,
    )


async def request_validation_error_handler(
    request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    """검증 실패 입력 원문을 제외하고 첫 번째 오류 위치만 제공한다."""
    errors = error.errors()
    first_error = errors[0] if errors else {}
    location = first_error.get("loc", ())
    field_parts = [
        str(part)
        for part in location
        if part not in {"body", "path", "query", "header", "cookie"}
    ]
    field = ".".join(field_parts) or None
    reason = first_error.get("type", "invalid")

    return _error_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="VALIDATION_ERROR",
        message="요청 값을 확인해 주세요.",
        field=field,
        details={"reason": reason},
    )


async def http_error_handler(
    request: Request,
    error: StarletteHTTPException,
) -> JSONResponse:
    """라우팅 및 HTTP 계층 오류도 동일한 오류 Envelope로 변환한다."""
    if error.status_code == status.HTTP_404_NOT_FOUND:
        code = "RESOURCE_NOT_FOUND"
        message = "요청한 리소스를 찾을 수 없습니다."
    elif error.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
        code = "METHOD_NOT_ALLOWED"
        message = "허용되지 않은 요청 방식입니다."
    else:
        code = "HTTP_ERROR"
        message = "요청을 처리할 수 없습니다."

    return _error_response(
        request,
        status_code=error.status_code,
        code=code,
        message=message,
    )


async def unexpected_error_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    """예상하지 못한 오류를 기록하되 내부 정보는 응답에서 숨긴다."""
    logger.error(
        "처리되지 않은 API 오류가 발생했습니다.",
        exc_info=error,
        extra={"request_id": get_request_id(request)},
    )
    return _error_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_SERVER_ERROR",
        message="요청 처리 중 오류가 발생했습니다.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """FastAPI 애플리케이션에 공통 예외 처리기를 등록한다."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
