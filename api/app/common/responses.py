"""JSON API의 공통 성공·오류 응답 모델과 생성 함수를 정의한다."""

from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from fastapi import Request
from pydantic import BaseModel, Field

from app.common.request_id import get_request_id


DataT = TypeVar("DataT")


class ApiMeta(BaseModel):
    """성공·오류 응답에 공통으로 포함하는 요청 메타데이터."""

    request_id: str
    timestamp: datetime


class ApiResponse(BaseModel, Generic[DataT]):
    """JSON API의 공통 성공 응답."""

    data: DataT
    meta: ApiMeta


class ApiError(BaseModel):
    """클라이언트가 코드로 분기할 수 있는 공통 오류 본문."""

    code: str
    message: str
    field: str | None = None
    retryable: bool = False
    next_action: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ApiErrorResponse(BaseModel):
    """JSON API의 공통 오류 응답."""

    error: ApiError
    meta: ApiMeta


COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
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


def api_meta(request: Request) -> ApiMeta:
    """현재 요청의 공통 메타데이터를 만든다."""
    return ApiMeta(
        request_id=get_request_id(request),
        timestamp=datetime.now(UTC),
    )


def success_response(request: Request, data: DataT) -> ApiResponse[DataT]:
    """라우터가 명시적으로 반환할 공통 성공 응답을 만든다."""
    return ApiResponse(data=data, meta=api_meta(request))
