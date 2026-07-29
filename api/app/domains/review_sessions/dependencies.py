"""검토 세션 기능 정책을 FastAPI에 주입한다."""

from typing import Annotated

from fastapi import Depends, Request

from app.domains.review_sessions.policy import (
    DEFAULT_REVIEW_SESSION_POLICY,
    ReviewSessionPolicy,
)


def get_review_session_policy(request: Request) -> ReviewSessionPolicy:
    """앱에 지정된 검토 세션 정책 또는 기본 정책을 반환한다."""
    policy = getattr(
        request.app.state,
        "review_session_policy",
        DEFAULT_REVIEW_SESSION_POLICY,
    )
    if not isinstance(policy, ReviewSessionPolicy):
        raise TypeError("review_session_policy는 ReviewSessionPolicy여야 합니다.")
    return policy


ReviewSessionPolicyDep = Annotated[
    ReviewSessionPolicy,
    Depends(get_review_session_policy),
]
"""업로드·세션 TTL 규칙이 필요한 Router와 Dependency에서 사용하는 정책."""
