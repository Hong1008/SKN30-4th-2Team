"""MCP progress 정규화와 서버 재시작 복구 검증."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from datetime import timedelta

import pytest
import asyncio
from contextlib import asynccontextmanager

from app.config import Settings
from app.core.db.database import Database
from app.lifespan import _recover_interrupted_reviews
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.domains.reviews.domain import Review, ReviewState
from app.domains.reviews.repository import SqlAlchemyReviewRepository
from app.domains.reviews.runner import (
    _progress_message,
    _weighted_progress,
    ReviewProgressRecorder,
    execute_review,
    normalize_review_result,
)
from app.core.storage.local import LocalFileStorage
from tests.domains.review_sessions.test_repository import review_session_entity
from tests.domains.reviews.test_repository import review_entity


class ProgressSession:
    def __init__(self, database: Database, review_id: str) -> None:
        self.database = database
        self.review_id = review_id
        self.percents: list[int] = []

    async def call_tool(
        self,
        _name,
        _arguments,
        read_timeout_seconds=None,
        progress_callback=None,
    ):
        for progress in (2, 7, 3):
            await progress_callback(
                progress,
                10,
                '{"stage":"CLAUSE_REVIEW"}',
            )
            with self.database.session() as db_session:
                review = SqlAlchemyReviewRepository(db_session).get(self.review_id)
                assert review is not None
                self.percents.append(review.progress["percent"])
        return {
            "status": "OK",
            "contract_type": "SW_FREELANCE",
            "clause_results": [],
            "missing_standard_clauses": [],
        }


class ResultSession:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    async def call_tool(
        self,
        _name,
        _arguments,
        read_timeout_seconds=None,
        progress_callback=None,
    ):
        return self.payload


class InspectingSession:
    def __init__(
        self,
        database: Database,
        review_id: str,
        payload: dict[str, object] | BaseException,
    ) -> None:
        self.database = database
        self.review_id = review_id
        self.payload = payload
        self.arguments = None

    async def call_tool(
        self,
        _name,
        arguments,
        read_timeout_seconds=None,
        progress_callback=None,
    ):
        self.arguments = arguments
        with self.database.session() as concurrent:
            review = SqlAlchemyReviewRepository(concurrent).get(self.review_id)
            assert review is not None
            review.expires_at += timedelta(seconds=1)
            SqlAlchemyReviewRepository(concurrent).save(review)
            concurrent.commit()
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


def _standard_clause() -> dict[str, str]:
    return {
        "clause_id": "std_1",
        "contract_type": "SW_FREELANCE",
        "category": "LIABILITY",
        "title": "손해배상",
        "text": "표준 책임 조항",
        "source": "SW 표준계약서",
        "version": "2025",
    }


def _valid_result() -> dict[str, object]:
    return {
        "status": "OK",
        "contract_type": "SW_FREELANCE",
        "clause_results": [
            {
                "user_clause": "제7조 책임 조항",
                "deviation": "NONE",
                "match": {
                    "status": "CANDIDATE_SELECTED",
                    "standard": _standard_clause(),
                    "score": 0.91,
                },
                "toxic_patterns": ["UNFAIR_DAMAGE_CLAIM"],
            },
            {
                "user_clause": "제8조 별도 합의",
                "deviation": "NO_MATCH",
                "match": {"status": "NO_CANDIDATE"},
                "toxic_patterns": [],
            },
        ],
        "missing_standard_clauses": [
            {"standard": {**_standard_clause(), "clause_id": "std_2"}}
        ],
        "message": None,
    }


def _settings() -> Settings:
    return Settings(
        app_env="local",
        llm_provider="ollama",
        llm_model="test",
    )


def _seed_executable_review(
    database: Database,
    tmp_path: Path,
    suffix: str,
) -> tuple[LocalFileStorage, Review]:
    storage = LocalFileStorage(tmp_path / f"uploads-{suffix}")
    storage_key = storage.save(BytesIO(b"contract"), extension="pdf")
    review_session = review_session_entity(f"ses_{suffix}")
    review_session.storage_key = storage_key
    review_session.selected_contract_type = "SW_FREELANCE"
    review = review_entity(
        f"rev_{suffix}",
        session_id=review_session.id,
        state=ReviewState.QUEUED,
    )
    with database.session() as session:
        SqlAlchemyReviewSessionRepository(session).add(review_session)
        session.commit()
        SqlAlchemyReviewRepository(session).add(review)
        session.commit()
    return storage, review


def test_structured_progress_separates_stage_and_display_message() -> None:
    assert _progress_message(
        '{"stage":"RERANK","message":"조항 재정렬 중"}',
        "BATCH_SEARCH",
    ) == ("RERANK", "조항 재정렬 중")
    assert _progress_message("알 수 없는 이전 MCP 문구", "RERANK") == (
        "RERANK",
        "알 수 없는 이전 MCP 문구",
    )


@pytest.mark.parametrize(
    ("stage", "current", "total", "expected"),
    [
        ("PREPARE", 0, 10, (0.0, 100.0)),
        ("BATCH_SEARCH", 0, 10, (5.0, 100.0)),
        ("RERANK", 0, 10, (25.0, 100.0)),
        ("RERANK", 1, 3, (38.33333333333333, 100.0)),
        ("RERANK", 2, 3, (51.666666666666664, 100.0)),
        ("RERANK", 3, 3, (65.0, 100.0)),
        ("CLAUSE_REVIEW", 3, 10, (71.0, 100.0)),
        ("MISSING_DETECTION", 10, 10, (95.0, 100.0)),
    ],
)
def test_progress_uses_stage_weighted_percent(
    stage: str,
    current: float,
    total: float,
    expected: tuple[float, float],
) -> None:
    assert _weighted_progress(stage, current, total) == expected


@pytest.mark.asyncio
async def test_progress_retries_once_after_ordinary_touch_cas_conflict(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review_session = review_session_entity("ses_progress_retry")
    review = review_entity(
        "rev_progress_retry",
        session_id=review_session.id,
    )
    with database.session() as setup:
        SqlAlchemyReviewSessionRepository(setup).add(review_session)
        setup.commit()
        SqlAlchemyReviewRepository(setup).add(review)
        setup.commit()

    original_save = SqlAlchemyReviewRepository.save
    first = True

    def save_with_one_touch(repository, entity):
        nonlocal first
        if first:
            first = False
            with database.session() as touching:
                touched = SqlAlchemyReviewRepository(touching).get(entity.id)
                assert touched is not None
                touched.expires_at += timedelta(microseconds=1)
                original_save(SqlAlchemyReviewRepository(touching), touched)
                touching.commit()
        return original_save(repository, entity)

    monkeypatch.setattr(
        SqlAlchemyReviewRepository,
        "save",
        save_with_one_touch,
    )

    await ReviewProgressRecorder(database, review.id)(
        1,
        2,
        '{"stage":"CLAUSE_REVIEW","message":"분류 중"}',
    )

    with database.session() as verification:
        restored = SqlAlchemyReviewRepository(verification).get(review.id)
    assert restored is not None
    assert restored.progress is not None
    assert restored.progress["stage"] == "CLAUSE_REVIEW"
    assert restored.progress["sequence"] == 2


def test_normalize_review_result_validates_real_mcp_dto_and_assigns_ids() -> None:
    result = normalize_review_result(
        _valid_result(),
        review_id="rev_01",
        toxic_pattern_labels={"UNFAIR_DAMAGE_CLAIM": "과도한 손해배상 표현"},
    )

    assert result["clause_results"][0] == {
        "user_clause_id": "uc_rev_01_1",
        "user_clause": "제7조 책임 조항",
        "deviation": "NONE",
        "match": {
            "status": "CANDIDATE_SELECTED",
            "standard": _standard_clause(),
            "score": 0.91,
        },
        "toxic_patterns": ["UNFAIR_DAMAGE_CLAIM"],
    }
    assert result["clause_results"][1]["user_clause_id"] == "uc_rev_01_2"
    assert [
        (item["user_clause"], item["deviation"])
        for item in result["clause_results"]
    ] == [
        ("제7조 책임 조항", "NONE"),
        ("제8조 별도 합의", "NO_MATCH"),
    ]
    assert result["missing_standard_clauses"] == [
        {"standard": {**_standard_clause(), "clause_id": "std_2"}}
    ]
    assert "toxic_patterns" not in result
    assert result["toxic_pattern_labels"] == {
        "UNFAIR_DAMAGE_CLAIM": "과도한 손해배상 표현"
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "OK", "contract_type": "SW_FREELANCE"},
        {
            "status": "OK",
            "contract_type": "SW_FREELANCE",
            "clause_results": None,
            "missing_standard_clauses": None,
        },
    ],
)
def test_normalize_review_result_defaults_missing_or_null_arrays(
    payload: dict[str, object],
) -> None:
    result = normalize_review_result(payload, review_id="rev_empty")

    assert result["clause_results"] == []
    assert result["missing_standard_clauses"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("clause_results", "broken"),
        ("clause_results", [1]),
        (
            "clause_results",
            [
                {
                    "user_clause": "조항",
                    "deviation": "UNKNOWN",
                    "match": {"status": "NO_CANDIDATE"},
                }
            ],
        ),
        (
            "clause_results",
            [
                {
                    "user_clause": "조항",
                    "deviation": "NONE",
                    "match": {"status": "NO_CANDIDATE"},
                }
            ],
        ),
        ("missing_standard_clauses", [1]),
        ("toxic_patterns", []),
    ],
)
def test_normalize_review_result_rejects_malformed_ok_payload(
    field: str,
    value: object,
) -> None:
    payload = _valid_result()
    payload[field] = value

    with pytest.raises(ValueError):
        normalize_review_result(payload, review_id="rev_invalid")


@pytest.mark.asyncio
async def test_execute_review_uses_monotonic_mcp_progress(
    database: Database,
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")
    storage_key = storage.save(BytesIO(b"contract"), extension="pdf")
    review_session = review_session_entity("ses_progress")
    review_session.storage_key = storage_key
    review_session.selected_contract_type = "SW_FREELANCE"
    review = review_entity(
        "rev_progress",
        session_id=review_session.id,
        state=ReviewState.QUEUED,
    )
    with database.session() as db_session:
        SqlAlchemyReviewSessionRepository(db_session).add(review_session)
        db_session.commit()
        SqlAlchemyReviewRepository(db_session).add(review)
        db_session.commit()
    progress_session = ProgressSession(database, review.id)
    runtime = SimpleNamespace(
        session=progress_session,
        tools=(),
        supports_file_path=False,
    )
    settings = Settings(
        app_env="local",
        llm_provider="ollama",
        llm_model="test",
    )

    await execute_review(
        database=database,
        storage=storage,
        runtime=runtime,
        settings=settings,
        review_id=review.id,
    )

    assert progress_session.percents == [69, 79, 79]
    with database.session() as db_session:
        completed = SqlAlchemyReviewRepository(db_session).get(review.id)
    assert completed is not None
    assert completed.state is ReviewState.COMPLETED
    assert completed.progress["sequence"] == 5
    assert completed.result["clause_results"] == []
    assert "toxic_patterns" not in completed.result


@pytest.mark.asyncio
async def test_execute_review_marks_malformed_ok_response_as_invalid(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")
    storage_key = storage.save(BytesIO(b"contract"), extension="pdf")
    review_session = review_session_entity("ses_invalid_result")
    review_session.storage_key = storage_key
    review_session.selected_contract_type = "SW_FREELANCE"
    review = review_entity(
        "rev_invalid_result",
        session_id=review_session.id,
        state=ReviewState.QUEUED,
    )
    with database.session() as db_session:
        SqlAlchemyReviewSessionRepository(db_session).add(review_session)
        db_session.commit()
        SqlAlchemyReviewRepository(db_session).add(review)
        db_session.commit()
    malformed = _valid_result()
    malformed["clause_results"] = "broken"
    original_delete = storage.delete
    delete_observed_committed_state = False

    def assert_committed_before_delete(storage_key_to_delete: str) -> None:
        nonlocal delete_observed_committed_state
        with database.session() as verification:
            stored_review = SqlAlchemyReviewRepository(verification).get(review.id)
            stored_session = SqlAlchemyReviewSessionRepository(
                verification
            ).get(review_session.id)
        assert stored_review is not None
        assert stored_review.state is ReviewState.FAILED
        assert stored_session is not None
        assert stored_session.storage_key is None
        delete_observed_committed_state = True
        original_delete(storage_key_to_delete)

    monkeypatch.setattr(storage, "delete", assert_committed_before_delete)
    runtime = SimpleNamespace(
        session=ResultSession(malformed),
        tools=(),
        supports_file_path=False,
    )

    await execute_review(
        database=database,
        storage=storage,
        runtime=runtime,
        settings=Settings(
            app_env="local",
            llm_provider="ollama",
            llm_model="test",
        ),
        review_id=review.id,
    )

    with database.session() as db_session:
        failed = SqlAlchemyReviewRepository(db_session).get(review.id)
    assert failed is not None
    assert failed.state is ReviewState.FAILED
    assert failed.mcp_review_status is None
    assert failed.result is None
    assert failed.error == {
        "code": "MCP_RESPONSE_INVALID",
        "retryable": False,
        "next_action": "CONTACT_SUPPORT",
    }
    assert delete_observed_committed_state is True


@pytest.mark.asyncio
async def test_execute_review_timeout_fails_without_success_progress(
    database: Database,
    tmp_path: Path,
) -> None:
    storage, review = _seed_executable_review(
        database,
        tmp_path,
        "timeout",
    )
    runtime = SimpleNamespace(
        session=InspectingSession(
            database,
            review.id,
            asyncio.TimeoutError(),
        ),
        tools=(),
        supports_file_path=False,
    )

    await execute_review(
        database=database,
        storage=storage,
        runtime=runtime,
        settings=_settings(),
        review_id=review.id,
    )

    with database.session() as session:
        failed = SqlAlchemyReviewRepository(session).get(review.id)
    assert failed is not None
    assert failed.state is ReviewState.FAILED
    assert failed.error["code"] == "MCP_TIMEOUT"
    assert failed.progress["percent"] < 100


@pytest.mark.asyncio
async def test_stdio_uses_storage_local_path_and_no_transaction_during_mcp(
    database: Database,
    tmp_path: Path,
) -> None:
    storage, review = _seed_executable_review(
        database,
        tmp_path,
        "stdio_boundary",
    )
    inspecting = InspectingSession(database, review.id, _valid_result())
    runtime = SimpleNamespace(
        session=inspecting,
        tools=(),
        supports_file_path=True,
    )

    await execute_review(
        database=database,
        storage=storage,
        runtime=runtime,
        settings=_settings(),
        review_id=review.id,
    )

    assert inspecting.arguments is not None
    assert "file_path" in inspecting.arguments
    assert "file_content" not in inspecting.arguments
    with database.session() as session:
        completed = SqlAlchemyReviewRepository(session).get(review.id)
    assert completed is not None
    assert completed.state is ReviewState.COMPLETED


@pytest.mark.asyncio
async def test_network_mcp_uses_file_content_and_original_file_name(
    database: Database,
    tmp_path: Path,
) -> None:
    storage, review = _seed_executable_review(
        database,
        tmp_path,
        "network_boundary",
    )
    inspecting = InspectingSession(database, review.id, _valid_result())
    runtime = SimpleNamespace(
        session=inspecting,
        tools=(),
        supports_file_path=False,
    )

    await execute_review(
        database=database,
        storage=storage,
        runtime=runtime,
        settings=_settings(),
        review_id=review.id,
    )

    assert inspecting.arguments is not None
    assert inspecting.arguments["file_content"] == "Y29udHJhY3Q="
    assert inspecting.arguments["file_name"] == "계약서.pdf"
    assert "file_path" not in inspecting.arguments


@pytest.mark.asyncio
async def test_cancelled_runner_does_not_store_final_result(
    database: Database,
    tmp_path: Path,
) -> None:
    storage, review = _seed_executable_review(
        database,
        tmp_path,
        "cancelled_runner",
    )
    entered = asyncio.Event()

    class BlockingSession:
        async def call_tool(
            self,
            _name,
            _arguments,
            read_timeout_seconds=None,
            progress_callback=None,
        ):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(
        execute_review(
            database=database,
            storage=storage,
            runtime=SimpleNamespace(
                session=BlockingSession(),
                tools=(),
                supports_file_path=False,
            ),
            settings=_settings(),
            review_id=review.id,
        )
    )
    await entered.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    with database.session() as session:
        interrupted = SqlAlchemyReviewRepository(session).get(review.id)
    assert interrupted is not None
    assert interrupted.state is ReviewState.REVIEWING
    assert interrupted.result is None


@pytest.mark.asyncio
async def test_cancelled_runner_closes_dedicated_mcp_runtime(
    database: Database,
    tmp_path: Path,
) -> None:
    """실행 취소 시 전용 stdio MCP 세션을 닫아 서버 작업도 종료한다."""
    storage, review = _seed_executable_review(
        database,
        tmp_path,
        "cancelled_dedicated_runtime",
    )
    entered = asyncio.Event()
    closed = asyncio.Event()

    class BlockingSession:
        async def call_tool(
            self,
            _name,
            _arguments,
            read_timeout_seconds=None,
            progress_callback=None,
        ):
            entered.set()
            await asyncio.Event().wait()

    @asynccontextmanager
    async def dedicated_runtime():
        try:
            yield SimpleNamespace(
                session=BlockingSession(),
                tools=(),
                supports_file_path=False,
            )
        finally:
            closed.set()

    task = asyncio.create_task(
        execute_review(
            database=database,
            storage=storage,
            runtime=SimpleNamespace(
                session=ResultSession(_valid_result()),
                tools=(),
                supports_file_path=False,
            ),
            settings=_settings(),
            review_id=review.id,
            runtime_factory=dedicated_runtime,
        )
    )
    await entered.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert closed.is_set()


def test_restart_marks_active_review_retryable(database: Database) -> None:
    review_session = review_session_entity("ses_restart")
    review = review_entity("rev_restart", session_id=review_session.id)
    with database.session() as db_session:
        SqlAlchemyReviewSessionRepository(db_session).add(review_session)
        db_session.commit()
        SqlAlchemyReviewRepository(db_session).add(review)
        db_session.commit()

    _recover_interrupted_reviews(database)

    with database.session() as db_session:
        recovered = SqlAlchemyReviewRepository(db_session).get(review.id)
    assert recovered is not None
    assert recovered.state is ReviewState.FAILED
    assert recovered.error == {
        "code": "REVIEW_INTERRUPTED",
        "retryable": True,
        "next_action": "RETRY_REVIEW",
    }
