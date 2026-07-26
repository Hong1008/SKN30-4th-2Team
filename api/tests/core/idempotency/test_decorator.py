"""@idempotent 데코레이터의 공통 멱등 처리 동작을 검증한다."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from app.core.db.database import Database
from app.core.common.errors import AppValidationError
from app.domains.review_sessions.domain import ReviewSession, ReviewSessionState
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository


class _FakeResponse(BaseModel):
    """테스트용 응답 모델."""

    review_id: str
    status: str = "ok"


def _seed_session(database: Database, session_id: str = "ses_deco") -> None:
    """테스트 세션을 DB에 생성한다."""
    now = datetime.now(UTC)
    with database.session() as session:
        SqlAlchemyReviewSessionRepository(session).add(
            ReviewSession(
                id=session_id,
                access_token_hash="hash",
                state=ReviewSessionState.READY_TO_REVIEW,
                original_file_name="contract.pdf",
                file_size_bytes=1,
                storage_key="key.pdf",
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(hours=1),
                selected_contract_type="SW_FREELANCE",
            )
        )
        session.commit()


def _fake_request() -> MagicMock:
    """FastAPI Request를 흉내 내는 Mock을 만든다."""
    request = MagicMock()
    request.state = MagicMock()
    # request_id는 success_response 내부에서 사용
    request.scope = {"state": {"request_id": "req_test"}}
    return request


# ── 1. 정상 처리 및 success_response 반환 ──


@pytest.mark.asyncio
async def test_idempotent_returns_success_response_on_first_call(
    database: Database,
) -> None:
    """데코레이터가 내부 함수 결과를 success_response로 래핑해 반환한다."""
    from app.core.idempotency.decorator import idempotent

    _seed_session(database)

    @idempotent(
        scope="test.create",
        response_model=_FakeResponse,
        get_session_id=lambda *, session_id, **kw: session_id,
        get_fingerprint_payload=lambda *, session_id, **kw: {"session_id": session_id},
    )
    async def handler(
        *, request, db_session, settings, session_id, idempotency_key=None
    ):
        return _FakeResponse(review_id="rev_1")

    request = _fake_request()
    with database.session() as db_session:
        result = await handler(
            request=request,
            db_session=db_session,
            settings=MagicMock(session_ttl_seconds=3600),
            session_id="ses_deco",
            idempotency_key="key-001",
        )

    assert result.data.review_id == "rev_1"
    assert result.meta is not None


# ── 2. Replay 시 이전 응답 반환 ──


@pytest.mark.asyncio
async def test_idempotent_returns_replay_on_duplicate_key(
    database: Database,
) -> None:
    """동일 키로 두 번째 호출 시 내부 함수를 실행하지 않고 저장된 응답을 반환한다."""
    from app.core.idempotency.decorator import idempotent

    _seed_session(database)
    call_count = 0

    @idempotent(
        scope="test.replay",
        response_model=_FakeResponse,
        get_session_id=lambda *, session_id, **kw: session_id,
        get_fingerprint_payload=lambda *, session_id, **kw: {"session_id": session_id},
    )
    async def handler(
        *, request, db_session, settings, session_id, idempotency_key=None
    ):
        nonlocal call_count
        call_count += 1
        return _FakeResponse(review_id="rev_once")

    settings = MagicMock(session_ttl_seconds=3600)
    common_kwargs = dict(
        settings=settings,
        session_id="ses_deco",
        idempotency_key="key-replay",
    )

    with database.session() as db_session:
        first = await handler(
            request=_fake_request(), db_session=db_session, **common_kwargs
        )
    with database.session() as db_session:
        second = await handler(
            request=_fake_request(), db_session=db_session, **common_kwargs
        )

    assert call_count == 1
    assert first.data.review_id == second.data.review_id == "rev_once"


# ── 3. use_guard=True 시 직렬화 동작 ──


@pytest.mark.asyncio
async def test_idempotent_guard_serializes_concurrent_calls(
    database: Database,
) -> None:
    """use_guard=True일 때 같은 키의 동시 호출이 직렬화되어 하나만 실행된다."""
    from app.core.idempotency.decorator import idempotent

    _seed_session(database)
    external_calls = 0

    @idempotent(
        scope="test.guard",
        response_model=_FakeResponse,
        get_session_id=lambda *, session_id, **kw: session_id,
        get_fingerprint_payload=lambda *, session_id, **kw: {"session_id": session_id},
        use_guard=True,
    )
    async def handler(
        *, request, db_session, settings, session_id, idempotency_key=None
    ):
        nonlocal external_calls
        external_calls += 1
        await asyncio.sleep(0)
        return _FakeResponse(review_id="rev_guard")

    settings = MagicMock(session_ttl_seconds=3600)

    async def call():
        with database.session() as db_session:
            return await handler(
                request=_fake_request(),
                db_session=db_session,
                settings=settings,
                session_id="ses_deco",
                idempotency_key="key-guard",
            )

    first, second = await asyncio.gather(call(), call())

    assert external_calls == 1
    assert first.data.review_id == second.data.review_id == "rev_guard"


# ── 4. use_guard=False 시 Guard 미적용 ──


@pytest.mark.asyncio
async def test_idempotent_without_guard_skips_lock(
    database: Database,
) -> None:
    """use_guard=False일 때 Guard 없이 직접 find_replay를 조회한다."""
    from app.core.idempotency.decorator import idempotent

    _seed_session(database)

    @idempotent(
        scope="test.noguard",
        response_model=_FakeResponse,
        get_session_id=lambda *, session_id, **kw: session_id,
        get_fingerprint_payload=lambda *, session_id, **kw: {"session_id": session_id},
        use_guard=False,
    )
    async def handler(
        *, request, db_session, settings, session_id, idempotency_key=None
    ):
        return _FakeResponse(review_id="rev_noguard")

    request = _fake_request()
    with database.session() as db_session:
        result = await handler(
            request=request,
            db_session=db_session,
            settings=MagicMock(session_ttl_seconds=3600),
            session_id="ses_deco",
            idempotency_key="key-noguard",
        )

    assert result.data.review_id == "rev_noguard"


# ── 5. post_commit 훅 호출 및 response_data 주입 검증 ──


@pytest.mark.asyncio
async def test_idempotent_calls_post_commit_with_response_data(
    database: Database,
) -> None:
    """commit 성공 후 post_commit 콜백이 response_data와 함께 호출된다."""
    from app.core.idempotency.decorator import idempotent

    _seed_session(database)
    captured: dict = {}

    def on_commit(*, response_data, **kwargs):
        captured["review_id"] = response_data.review_id
        captured["called"] = True

    @idempotent(
        scope="test.postcommit",
        response_model=_FakeResponse,
        get_session_id=lambda *, session_id, **kw: session_id,
        get_fingerprint_payload=lambda *, session_id, **kw: {"session_id": session_id},
        use_guard=False,
        post_commit=on_commit,
    )
    async def handler(
        *, request, db_session, settings, session_id, idempotency_key=None
    ):
        return _FakeResponse(review_id="rev_post")

    with database.session() as db_session:
        await handler(
            request=_fake_request(),
            db_session=db_session,
            settings=MagicMock(session_ttl_seconds=3600),
            session_id="ses_deco",
            idempotency_key="key-post",
        )

    assert captured["called"] is True
    assert captured["review_id"] == "rev_post"


@pytest.mark.asyncio
async def test_idempotent_post_commit_not_called_on_replay(
    database: Database,
) -> None:
    """Replay 반환 시 post_commit은 호출되지 않는다."""
    from app.core.idempotency.decorator import idempotent

    _seed_session(database)
    post_commit_calls = 0

    def on_commit(*, response_data, **kwargs):
        nonlocal post_commit_calls
        post_commit_calls += 1

    @idempotent(
        scope="test.noreplay_post",
        response_model=_FakeResponse,
        get_session_id=lambda *, session_id, **kw: session_id,
        get_fingerprint_payload=lambda *, session_id, **kw: {"session_id": session_id},
        use_guard=False,
        post_commit=on_commit,
    )
    async def handler(
        *, request, db_session, settings, session_id, idempotency_key=None
    ):
        return _FakeResponse(review_id="rev_no_replay_post")

    settings = MagicMock(session_ttl_seconds=3600)
    common = dict(settings=settings, session_id="ses_deco")

    with database.session() as db_session:
        await handler(
            request=_fake_request(),
            db_session=db_session,
            idempotency_key="key-replay-post",
            **common,
        )
    with database.session() as db_session:
        await handler(
            request=_fake_request(),
            db_session=db_session,
            idempotency_key="key-replay-post",
            **common,
        )

    assert post_commit_calls == 1


# ── 6. request.state.idempotency_key 주입 검증 ──


@pytest.mark.asyncio
async def test_idempotent_injects_key_into_request_state(
    database: Database,
) -> None:
    """데코레이터가 검증된 키를 request.state.idempotency_key에 저장한다."""
    from app.core.idempotency.decorator import idempotent

    _seed_session(database)
    captured_key: str | None = None

    @idempotent(
        scope="test.state_key",
        response_model=_FakeResponse,
        get_session_id=lambda *, session_id, **kw: session_id,
        get_fingerprint_payload=lambda *, session_id, **kw: {"session_id": session_id},
    )
    async def handler(
        *, request, db_session, settings, session_id, idempotency_key=None
    ):
        nonlocal captured_key
        captured_key = request.state.idempotency_key
        return _FakeResponse(review_id="rev_state")

    request = _fake_request()
    with database.session() as db_session:
        await handler(
            request=request,
            db_session=db_session,
            settings=MagicMock(session_ttl_seconds=3600),
            session_id="ses_deco",
            idempotency_key="  my-key-123  ",
        )

    assert captured_key == "my-key-123"


# ── 7. Key 검증 실패 시 예외 전파 ──


@pytest.mark.asyncio
async def test_idempotent_raises_on_missing_key(database: Database) -> None:
    """Idempotency-Key가 없으면 AppValidationError를 발생시킨다."""
    from app.core.idempotency.decorator import idempotent

    @idempotent(
        scope="test.nokey",
        response_model=_FakeResponse,
        get_session_id=lambda *, session_id, **kw: session_id,
        get_fingerprint_payload=lambda *, session_id, **kw: {"session_id": session_id},
    )
    async def handler(
        *, request, db_session, settings, session_id, idempotency_key=None
    ):
        return _FakeResponse(review_id="should_not_reach")

    with pytest.raises(AppValidationError):
        with database.session() as db_session:
            await handler(
                request=_fake_request(),
                db_session=db_session,
                settings=MagicMock(session_ttl_seconds=3600),
                session_id="ses_deco",
                idempotency_key=None,
            )


@pytest.mark.asyncio
async def test_idempotent_raises_on_empty_key(database: Database) -> None:
    """빈 문자열 키는 AppValidationError를 발생시킨다."""
    from app.core.idempotency.decorator import idempotent

    @idempotent(
        scope="test.emptykey",
        response_model=_FakeResponse,
        get_session_id=lambda *, session_id, **kw: session_id,
        get_fingerprint_payload=lambda *, session_id, **kw: {"session_id": session_id},
    )
    async def handler(
        *, request, db_session, settings, session_id, idempotency_key=None
    ):
        return _FakeResponse(review_id="should_not_reach")

    with pytest.raises(AppValidationError):
        with database.session() as db_session:
            await handler(
                request=_fake_request(),
                db_session=db_session,
                settings=MagicMock(session_ttl_seconds=3600),
                session_id="ses_deco",
                idempotency_key="   ",
            )


@pytest.mark.asyncio
async def test_idempotent_supports_idempotency_context(
    database: Database,
) -> None:
    """IdempotencyContext 객체를 주입받았을 때 정상적으로 멱등 처리를 수행한다."""
    from app.core.idempotency.decorator import IdempotencyContext, idempotent

    _seed_session(database)

    @idempotent(
        scope="test.context_dep",
        response_model=_FakeResponse,
        get_session_id=lambda *, session_id, **kw: session_id,
        get_fingerprint_payload=lambda *, session_id, **kw: {"session_id": session_id},
    )
    async def handler(*, idem_ctx, session_id):
        return _FakeResponse(review_id="rev_context")

    request = _fake_request()
    with database.session() as db_session:
        idem_ctx = IdempotencyContext(
            request=request,
            db_session=db_session,
            settings=MagicMock(session_ttl_seconds=3600),
            idempotency_key="key-ctx-001",
        )
        result = await handler(idem_ctx=idem_ctx, session_id="ses_deco")

    assert result.data.review_id == "rev_context"
    assert request.state.idempotency_key == "key-ctx-001"

