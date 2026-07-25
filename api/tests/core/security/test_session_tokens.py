"""익명 세션 접근 토큰의 생성·해시·Cookie 정책을 검증한다."""

from fastapi import Response

from app.config import Settings
from app.core.db.database import Database
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.core.security.cookies import SESSION_ACCESS_COOKIE, issue_session_access
from app.core.security.session_tokens import (
    access_token_matches,
    issue_access_token,
)
from tests.review_sessions.test_repository import review_session_entity


def test_access_token_is_random_and_only_digest_is_reusable() -> None:
    first = issue_access_token()
    second = issue_access_token()

    assert first.raw != second.raw
    assert first.digest != second.digest
    assert len(first.digest) == 64
    assert access_token_matches(first.raw, first.digest) is True
    assert access_token_matches(second.raw, first.digest) is False
    assert first.raw not in first.digest


def test_session_cookie_is_http_only_and_not_in_response_body() -> None:
    settings = Settings(app_env="local", llm_provider="openai")
    response = Response()
    access = issue_session_access(response, settings=settings)

    cookie = response.headers["set-cookie"]
    assert f"{SESSION_ACCESS_COOKIE}={access.raw}" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/api/v1" in cookie
    assert access.raw not in response.body.decode()
    assert len(access.digest) == 64


def test_database_stores_only_access_token_digest(database: Database) -> None:
    token = issue_access_token()
    entity = review_session_entity("ses_token_hash")
    entity.access_token_hash = token.digest

    with database.session() as session:
        SqlAlchemyReviewSessionRepository(session).add(entity)
        session.commit()

    with database.engine.connect() as connection:
        stored = connection.exec_driver_sql(
            "SELECT access_token_hash FROM review_sessions WHERE id = ?",
            (entity.id,),
        ).scalar_one()

    assert stored == token.digest
    assert stored != token.raw
