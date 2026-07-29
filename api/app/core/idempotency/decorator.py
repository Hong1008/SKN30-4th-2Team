"""라우터 멱등 처리를 공통화하는 AOP 데코레이터."""

from collections.abc import Callable
from contextlib import nullcontext
from functools import wraps
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from pydantic import BaseModel

from app.config import SettingsDep
from app.core.common.responses import success_response
from app.core.db.dependencies import DbSessionDep
from app.core.idempotency.service import (
    find_replay,
    idempotency_guard,
    request_fingerprint,
    require_idempotency_key,
    save_response,
)
from app.domains.review_sessions.dependencies import ReviewSessionPolicyDep
from app.domains.review_sessions.policy import DEFAULT_REVIEW_SESSION_POLICY


@dataclass(slots=True)
class IdempotencyContext:
    """멱등 처리에 필요한 공통 의존성을 단일 객체로 묶는다."""

    request: Request
    db_session: DbSessionDep
    settings: SettingsDep
    review_session_policy: ReviewSessionPolicyDep = DEFAULT_REVIEW_SESSION_POLICY
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")


IdempotencyContextDep = Annotated[IdempotencyContext, Depends()]


def idempotent(
    *,
    scope: str,
    response_model: type[BaseModel],
    get_session_id: Callable[..., str],
    get_fingerprint_payload: Callable[..., Any] | None = None,
    use_guard: bool = True,
    post_commit: Callable[..., None] | None = None,
):
    """라우터 함수의 멱등 처리를 공통화하는 데코레이터.

    이 데코레이터를 적용하는 라우터 핸들러는 ``idem_ctx: IdempotencyContextDep`` 를
    파라미터로 포함하거나, 개별 의존성(request, db_session, settings, idempotency_key)을
    선언해야 합니다.

    Parameters
    ----------
    scope:
        멱등 키 저장 범위 (예: ``"reviews.chat"``).
    response_model:
        Replay 시 스냅샷 검증용 Pydantic 모델.
    get_session_id:
        라우터 ``**kwargs`` 에서 ``session_id`` 를 추출하는 함수.
    get_fingerprint_payload:
        fingerprint 대상을 추출하는 함수. ``None`` 이면
        ``kwargs["payload"].model_dump(mode="json")`` 을 사용한다.
    use_guard:
        ``idempotency_guard`` 인메모리 Lock 사용 여부.
    post_commit:
        DB commit 성공 후 실행할 콜백. 데코레이터가 ``response_data``
        (내부 함수 반환값)를 추가 주입한다.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            idem_ctx = kwargs.get("idem_ctx") or next(
                (v for v in kwargs.values() if isinstance(v, IdempotencyContext)), None
            )
            if idem_ctx is not None:
                request = idem_ctx.request
                db_session = idem_ctx.db_session
                review_session_policy = idem_ctx.review_session_policy
                idempotency_key_raw = idem_ctx.idempotency_key
            else:
                request = kwargs["request"]
                db_session = kwargs["db_session"]
                review_session_policy = kwargs.get(
                    "review_session_policy",
                    DEFAULT_REVIEW_SESSION_POLICY,
                )
                idempotency_key_raw = kwargs.get("idempotency_key")

            # 1. 키 검증 및 request.state 주입
            key = require_idempotency_key(idempotency_key_raw)
            request.state.idempotency_key = key

            # 2. session_id 및 fingerprint 추출
            session_id = get_session_id(**kwargs)
            if get_fingerprint_payload is not None:
                fp_payload = get_fingerprint_payload(**kwargs)
            else:
                fp_payload = kwargs["payload"].model_dump(mode="json")
            fingerprint = request_fingerprint(fp_payload)

            # 3. Guard 적용 여부에 따라 context manager 결정
            if use_guard:
                guard_cm = idempotency_guard(
                    scope=scope,
                    session_id=session_id,
                    idempotency_key=key,
                )
            else:
                guard_cm = nullcontext()

            async with guard_cm:
                # 4. 이전 응답 조회
                replay = find_replay(
                    db_session,
                    scope=scope,
                    session_id=session_id,
                    idempotency_key=key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return success_response(
                        request,
                        response_model.model_validate(replay),
                    )

                # 5. 비즈니스 로직 실행
                response_data = await func(*args, **kwargs)

                # 6. 응답 스냅샷 저장
                raced_replay = save_response(
                    db_session,
                    scope=scope,
                    session_id=session_id,
                    idempotency_key=key,
                    fingerprint=fingerprint,
                    response_snapshot=response_data.model_dump(mode="json"),
                    ttl_seconds=review_session_policy.session_ttl_seconds,
                )
                if raced_replay is not None:
                    return success_response(
                        request,
                        response_model.model_validate(raced_replay),
                    )

                # 7. Commit 및 post_commit 훅
                db_session.commit()
                if post_commit is not None:
                    post_commit(**kwargs, response_data=response_data)

                return success_response(request, response_data)

        return wrapper

    return decorator
