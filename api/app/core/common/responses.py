"""JSON API의 공통 성공·오류 응답 모델과 생성 함수를 정의한다."""

from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from fastapi import Request
from pydantic import BaseModel, Field

from app.core.common.request_id import get_request_id


DataT = TypeVar("DataT")


class ApiMeta(BaseModel):
    """성공·오류 응답에 공통으로 포함하는 요청 메타데이터."""

    request_id: str = Field(description="요청 고유 식별자")
    timestamp: datetime = Field(description="응답 생성 일시 (ISO 8601)")


class ApiResponse(BaseModel, Generic[DataT]):
    """JSON API의 공통 성공 응답."""

    data: DataT = Field(description="성공 응답 데이터 본문")
    meta: ApiMeta = Field(description="요청 메타데이터")


class ApiError(BaseModel):
    """클라이언트가 코드로 분기할 수 있는 공통 오류 본문."""

    code: str = Field(description="에러 코드 (예: MCP_TIMEOUT, IDEMPOTENCY_KEY_REUSED)")
    message: str = Field(description="사용자 노출용 오류 메시지")
    field: str | None = Field(default=None, description="오류 관련 요청 필드명")
    retryable: bool = Field(default=False, description="재시도 가능 여부")
    next_action: str | None = Field(default=None, description="권장 다음 행동 코드")
    details: dict[str, Any] = Field(default_factory=dict, description="오류 상세 정보")


class ApiErrorResponse(BaseModel):
    """JSON API의 공통 오류 응답."""

    error: ApiError = Field(description="오류 정보 본문")
    meta: ApiMeta = Field(description="요청 메타데이터")


COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    429: {"model": ApiErrorResponse, "description": "작업 처리 또는 대기 용량 초과"},
    404: {
        "model": ApiErrorResponse,
        "description": "리소스가 없거나 현재 익명 세션에서 접근할 수 없음",
    },
    409: {"model": ApiErrorResponse, "description": "현재 상태 또는 멱등 키 충돌"},
    410: {"model": ApiErrorResponse, "description": "익명 세션 만료"},
    422: {"model": ApiErrorResponse, "description": "요청 값 검증 실패"},
    503: {"model": ApiErrorResponse, "description": "외부 서비스 사용 불가"},
    504: {"model": ApiErrorResponse, "description": "외부 서비스 시간 초과"},
}


UPLOAD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    429: {
        "model": ApiErrorResponse,
        "description": "동시 업로드 처리 용량 초과 (UPLOAD_CAPACITY_EXCEEDED)",
    },
    422: {
        "model": ApiErrorResponse,
        "description": (
            "업로드 입력 또는 파일 내용 검증 실패 "
            "(FILE_EXTENSION_MISSING, ENCRYPTED_FILE, CORRUPTED_FILE, VALIDATION_ERROR)"
        ),
    },
    413: {
        "model": ApiErrorResponse,
        "description": "업로드 파일이 최대 허용 크기를 초과함 (FILE_TOO_LARGE)",
    },
    415: {
        "model": ApiErrorResponse,
        "description": (
            "지원하지 않는 확장자 또는 확장자와 실제 형식 불일치 "
            "(UNSUPPORTED_FILE_TYPE, FILE_TYPE_MISMATCH)"
        ),
    },
}


def api_meta(request: Request) -> ApiMeta:
    """현재 요청의 공통 메타데이터를 만든다."""
    return ApiMeta(
        request_id=get_request_id(request),
        timestamp=datetime.now(UTC),
    )


def success_response(request: Request, data: DataT) -> ApiResponse[DataT]:
    """라우터가 명시적으로 반환할 공통 성공 응답을 만든다."""
    return ApiResponse(data=data, meta=api_meta(request))
