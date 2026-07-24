"""요청 단위 식별자를 생성하고 응답 헤더로 전달한다."""

from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response


REQUEST_ID_HEADER = "X-Request-ID"


def new_request_id() -> str:
    """추측 가능한 사용자 정보가 없는 요청 식별자를 생성한다."""
    return f"req_{uuid4().hex}"


def get_request_id(request: Request) -> str:
    """현재 요청 식별자를 반환하며 미들웨어 밖에서는 새로 생성한다."""
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str):
        return request_id

    request_id = new_request_id()
    request.state.request_id = request_id
    return request_id


async def add_request_id(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """요청에 서버 생성 ID를 부여하고 같은 값을 응답 헤더에 싣는다."""
    request.state.request_id = new_request_id()
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = get_request_id(request)
    return response


def register_request_id_middleware(app: FastAPI) -> None:
    """FastAPI 애플리케이션에 요청 ID 미들웨어를 등록한다."""
    app.middleware("http")(add_request_id)
