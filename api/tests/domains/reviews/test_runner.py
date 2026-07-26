"""MCP progress 정규화와 서버 재시작 복구 검증."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.core.db.database import Database
from app.lifespan import _recover_interrupted_reviews
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.domains.reviews.domain import ReviewState
from app.domains.reviews.repository import SqlAlchemyReviewRepository
from app.domains.reviews.runner import execute_review, normalize_review_result
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


def test_normalize_review_result_validates_real_mcp_dto_and_assigns_ids() -> None:
    result = normalize_review_result(_valid_result(), review_id="rev_01")

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
    assert result["missing_standard_clauses"] == [
        {"standard": {**_standard_clause(), "clause_id": "std_2"}}
    ]
    assert "toxic_patterns" not in result


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
    review = review_entity("rev_progress", session_id=review_session.id)
    review.state = ReviewState.QUEUED
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

    assert progress_session.percents == [20, 70, 70]
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
) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")
    storage_key = storage.save(BytesIO(b"contract"), extension="pdf")
    review_session = review_session_entity("ses_invalid_result")
    review_session.storage_key = storage_key
    review_session.selected_contract_type = "SW_FREELANCE"
    review = review_entity("rev_invalid_result", session_id=review_session.id)
    review.state = ReviewState.QUEUED
    with database.session() as db_session:
        SqlAlchemyReviewSessionRepository(db_session).add(review_session)
        db_session.commit()
        SqlAlchemyReviewRepository(db_session).add(review)
        db_session.commit()
    malformed = _valid_result()
    malformed["clause_results"] = "broken"
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


def test_restart_marks_active_review_retryable(database: Database) -> None:
    review_session = review_session_entity("ses_restart")
    review = review_entity("rev_restart", session_id=review_session.id)
    review.state = ReviewState.REVIEWING
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
