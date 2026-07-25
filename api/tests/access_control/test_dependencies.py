"""Cookie 기반 세션·리뷰 소유권 검증을 API 경계에서 확인한다."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from app.access_control.dependencies import OwnedReviewDep, OwnedReviewSessionDep
from app.common.exception_handlers import register_exception_handlers
from app.db.database import Database
from app.db.dependencies import get_database
from app.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.reviews.repository import SqlAlchemyReviewRepository
from app.reviews.domain import ReviewState
from app.security.cookies import SESSION_ACCESS_COOKIE
from app.security.session_tokens import hash_access_token
from tests.review_sessions.test_repository import review_session_entity
from tests.reviews.test_repository import review_entity


pytestmark = pytest.mark.asyncio


def _create_app(database: Database) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_database] = lambda: database

    @app.get("/sessions/{session_id}")
    def get_session(owned: OwnedReviewSessionDep) -> dict[str, str]:
        return {"session_id": owned.id}

    @app.get("/reviews/{review_id}")
    def get_review(owned: OwnedReviewDep) -> dict[str, str]:
        return {"review_id": owned.id}

    return app


def _seed(database: Database) -> tuple[str, str, str]:
    owner_token = "owner-access-token"
    other_token = "other-access-token"
    review_session = review_session_entity("ses_owner")
    review_session.access_token_hash = hash_access_token(owner_token)
    review = review_entity("rev_owner", session_id=review_session.id)
    with database.session() as session:
        SqlAlchemyReviewSessionRepository(session).add(review_session)
        session.commit()
        SqlAlchemyReviewRepository(session).add(review)
        session.commit()
    return owner_token, other_token, review.id


@pytest.mark.parametrize(
    ("path", "resource_id"),
    [
        ("/sessions/{resource_id}", "ses_owner"),
        ("/reviews/{resource_id}", "rev_owner"),
    ],
)
async def test_only_owner_cookie_can_access_resource(
    database: Database,
    path: str,
    resource_id: str,
) -> None:
    owner_token, other_token, _ = _seed(database)
    transport = httpx.ASGITransport(app=_create_app(database))
    url = path.format(resource_id=resource_id)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        without_cookie = await client.get(url)
        client.cookies.set(SESSION_ACCESS_COOKIE, other_token)
        other_browser = await client.get(url)
        client.cookies.set(SESSION_ACCESS_COOKIE, owner_token)
        owner = await client.get(url)

    assert without_cookie.status_code == 404
    assert other_browser.status_code == 404
    assert without_cookie.json()["error"] == other_browser.json()["error"]
    assert owner.status_code == 200


async def test_owned_expired_session_returns_410_but_other_browser_gets_404(
    database: Database,
) -> None:
    owner_token, other_token, _ = _seed(database)
    with database.session() as session:
        review_repository = SqlAlchemyReviewRepository(session)
        review = review_repository.get("rev_owner")
        assert review is not None
        review.state = ReviewState.COMPLETED
        review_repository.save(review)
        repository = SqlAlchemyReviewSessionRepository(session)
        entity = repository.get("ses_owner")
        assert entity is not None
        entity.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        repository.save(entity)
        session.commit()

    transport = httpx.ASGITransport(app=_create_app(database))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        client.cookies.set(SESSION_ACCESS_COOKIE, owner_token)
        owner = await client.get("/sessions/ses_owner")
        client.cookies.set(SESSION_ACCESS_COOKIE, other_token)
        other_browser = await client.get("/sessions/ses_owner")

    assert owner.status_code == 410
    assert owner.json()["error"]["code"] == "SESSION_EXPIRED"
    assert other_browser.status_code == 404
