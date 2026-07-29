"""익명 세션 접근 토큰의 HttpOnly Cookie 발급 정책."""

from fastapi import Response

from app.config import Settings
from app.core.security.session_tokens import SessionAccessToken, issue_access_token
from app.domains.review_sessions.policy import (
    DEFAULT_REVIEW_SESSION_POLICY,
    ReviewSessionPolicy,
)


SESSION_ACCESS_COOKIE = "workshield_session"


def issue_session_access(
    response: Response,
    *,
    settings: Settings,
    policy: ReviewSessionPolicy = DEFAULT_REVIEW_SESSION_POLICY,
) -> SessionAccessToken:
    """접근 토큰을 생성하고 원본은 HttpOnly Cookie로만 전달한다."""
    access = issue_access_token()
    set_session_access_cookie(
        response,
        token=access.raw,
        settings=settings,
        policy=policy,
    )
    return access


def set_session_access_cookie(
    response: Response,
    *,
    token: str,
    settings: Settings,
    policy: ReviewSessionPolicy = DEFAULT_REVIEW_SESSION_POLICY,
) -> None:
    """원본 접근 토큰을 응답 본문이 아닌 HttpOnly Cookie로만 전달한다."""
    response.set_cookie(
        key=SESSION_ACCESS_COOKIE,
        value=token,
        max_age=policy.session_ttl_seconds,
        httponly=True,
        secure=settings.app_env == "prod",
        samesite="lax",
        path="/api/v1",
    )


def clear_session_access_cookie(response: Response, settings: Settings) -> None:
    """현재 익명 세션 Cookie를 만료시킨다."""
    response.delete_cookie(
        key=SESSION_ACCESS_COOKIE,
        httponly=True,
        secure=settings.app_env == "prod",
        samesite="lax",
        path="/api/v1",
    )
