"""세션 Cookie와 리소스 소유권을 검증하는 공통 FastAPI Dependency."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import APIKeyCookie

from app.common.errors import ExpiredError, NotFoundError
from app.config import SettingsDep
from app.db.dependencies import DbSessionDep
from app.review_sessions.activity import touch_review, touch_session
from app.review_sessions.domain import ReviewSession
from app.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.reviews.domain import Review
from app.reviews.repository import SqlAlchemyReviewRepository
from app.security.cookies import SESSION_ACCESS_COOKIE
from app.security.session_tokens import hash_access_token


session_cookie_scheme = APIKeyCookie(
    name=SESSION_ACCESS_COOKIE,
    auto_error=False,
)
SessionCookie = Annotated[
    str | None,
    Security(session_cookie_scheme),
]


def _resource_not_found() -> NotFoundError:
    """존재 여부와 접근 가능 여부를 구분하지 않는 공통 404를 만든다."""
    return NotFoundError(
        code="RESOURCE_NOT_FOUND",
        message="요청한 리소스를 찾을 수 없습니다.",
    )


def resolve_owned_session(
    session_id: str,
    access_token: str | None,
    db_session,
) -> ReviewSession:
    """주어진 Cookie가 소유한 미만료 세션을 반환한다."""
    if not access_token:
        raise _resource_not_found()

    entity = SqlAlchemyReviewSessionRepository(db_session).get_owned(
        session_id,
        hash_access_token(access_token),
    )
    if entity is None:
        raise _resource_not_found()
    if (
        entity.is_expired(datetime.now(UTC))
        and not SqlAlchemyReviewRepository(db_session).has_active_for_session(entity.id)
    ):
        raise ExpiredError(
            code="SESSION_EXPIRED",
            message="검토 세션이 만료되었습니다.",
            next_action="START_NEW_REVIEW",
        )
    return entity


def resolve_owned_review(
    review_id: str,
    access_token: str | None,
    db_session,
) -> Review:
    """주어진 Cookie가 소유한 미만료 검토를 반환한다."""
    if not access_token:
        raise _resource_not_found()

    entity = SqlAlchemyReviewRepository(db_session).get_owned(
        review_id,
        hash_access_token(access_token),
    )
    if entity is None:
        raise _resource_not_found()
    if (
        entity.state.value not in {"QUEUED", "REVIEWING"}
        and entity.is_expired(datetime.now(UTC))
    ):
        raise ExpiredError(
            code="SESSION_EXPIRED",
            message="검토 세션이 만료되었습니다.",
            next_action="START_NEW_REVIEW",
        )
    return entity


def require_owned_review_session(
    session_id: str,
    db_session: DbSessionDep,
    settings: SettingsDep,
    access_token: SessionCookie = None,
) -> ReviewSession:
    """Cookie 토큰이 소유한 미만료 검토 세션만 반환한다."""
    entity = resolve_owned_session(session_id, access_token, db_session)
    touch_session(
        db_session,
        entity,
        ttl_seconds=settings.session_ttl_seconds,
    )
    db_session.commit()
    return entity


OwnedReviewSessionDep = Annotated[
    ReviewSession,
    Depends(require_owned_review_session),
]


def require_owned_review(
    review_id: str,
    db_session: DbSessionDep,
    settings: SettingsDep,
    access_token: SessionCookie = None,
) -> Review:
    """Cookie 토큰이 소유한 미만료 검토만 반환한다."""
    entity = resolve_owned_review(review_id, access_token, db_session)
    touch_review(
        db_session,
        entity,
        ttl_seconds=settings.session_ttl_seconds,
    )
    db_session.commit()
    return entity


OwnedReviewDep = Annotated[Review, Depends(require_owned_review)]
