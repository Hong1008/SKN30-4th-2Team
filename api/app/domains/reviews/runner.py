"""백그라운드 MCP 전체 검토 실행기와 실제 progress 연결."""

import asyncio
import base64
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncContextManager

from app.config import Settings
from app.core.db.database import Database
from app.core.llm.mcp.types import WorkShieldMCPRuntime
from app.domains.review_sessions.activity import resume_ttl_after_review
from app.domains.review_sessions.policy import (
    DEFAULT_REVIEW_SESSION_POLICY,
    ReviewSessionPolicy,
)
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.domains.review_sessions.service import _tool_payload
from app.domains.reviews.domain import MCPReviewStatus, ReviewState
from app.domains.reviews.repository import (
    ConcurrentReviewUpdateError,
    SqlAlchemyReviewRepository,
)
from app.domains.reviews.schemas import (
    MCPReviewResult,
    NormalizedReviewResult,
    ReviewClauseResult,
)
from app.core.storage.protocol import FileStorage


logger = logging.getLogger("uvicorn.error")


class InvalidMCPReviewResultError(ValueError):
    """MCP 전체 검토 응답이 공개 DTO를 위반했음을 나타낸다."""


_PROGRESS_STAGE_RANGES: dict[str, tuple[float, float]] = {
    "PREPARE": (0.0, 5.0),
    "BATCH_SEARCH": (5.0, 25.0),
    "RERANK": (25.0, 65.0),
    "CLAUSE_REVIEW": (65.0, 85.0),
    "MISSING_DETECTION": (85.0, 95.0),
    "RESULT_ASSEMBLY": (95.0, 99.0),
}


def _mcp_status(payload: dict[str, Any]) -> MCPReviewStatus:
    raw = str(payload.get("status", "PIPELINE_ERROR")).upper()
    try:
        return MCPReviewStatus(raw)
    except ValueError:
        return MCPReviewStatus.PIPELINE_ERROR


def normalize_review_result(
    payload: dict[str, Any],
    *,
    review_id: str,
    toxic_pattern_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """실제 MCP 공개 DTO를 검증하고 API 소유 조항 ID를 결합한다."""
    try:
        mcp_result = MCPReviewResult.model_validate(payload)
    except ValueError as error:
        raise InvalidMCPReviewResultError from error
    normalized = NormalizedReviewResult(
        status=mcp_result.status,
        contract_type=mcp_result.contract_type,
        clause_results=[
            ReviewClauseResult(
                user_clause_id=f"uc_{review_id}_{index}",
                **clause.model_dump(),
            )
            for index, clause in enumerate(mcp_result.clause_results, start=1)
        ],
        missing_standard_clauses=mcp_result.missing_standard_clauses,
        toxic_pattern_labels=toxic_pattern_labels or {},
        message=mcp_result.message,
    )
    return normalized.model_dump(mode="json")


async def _toxic_pattern_label_snapshot(
    runtime: WorkShieldMCPRuntime,
    *,
    timeout_seconds: float,
) -> dict[str, str]:
    """MCP가 이미 정의한 주의 신호 title만 검토 스냅샷에 보관한다."""
    tool = next(
        (
            candidate
            for candidate in runtime.tools
            if candidate.name == "list_toxic_pattern_details"
        ),
        None,
    )
    if tool is None:
        return {}
    try:
        payload = _tool_payload(
            await asyncio.wait_for(tool.ainvoke({}), timeout=timeout_seconds)
        )
    except Exception:
        return {}
    patterns = payload.get("patterns")
    if not isinstance(patterns, list):
        return {}
    return {
        code: title
        for item in patterns
        if isinstance(item, dict)
        and isinstance((code := item.get("pattern")), str)
        and isinstance((title := item.get("title")), str)
        and code
        and title
    }


def _progress_message(
    message: str | None,
    previous_stage: str,
) -> tuple[str, str | None]:
    """구조화 progress에서 stage와 사용자 표시 문구를 분리한다."""
    if not message:
        return previous_stage, None
    try:
        parsed = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        stage = parsed.get("stage")
        display_message = parsed.get("message")
        return (
            stage.upper() if isinstance(stage, str) else previous_stage,
            display_message if isinstance(display_message, str) else message,
        )
    upper = message.upper()
    for stage in (
        "PREPARE",
        "BATCH_SEARCH",
        "RERANK",
        "CLAUSE_REVIEW",
        "MISSING_DETECTION",
        "RESULT_ASSEMBLY",
    ):
        if stage in upper:
            return stage, message
    return previous_stage, message


def _weighted_progress(
    stage: str,
    current: float,
    total: float | None,
) -> tuple[float, float | None]:
    """MCP 단계 내부 진행량을 화면용 전체 진행률 구간으로 변환한다."""
    stage_range = _PROGRESS_STAGE_RANGES.get(stage)
    if stage_range is None:
        return current, total

    start, end = stage_range
    ratio = 0.0
    if total is not None and total > 0:
        ratio = min(max(current / total, 0.0), 1.0)
    weighted_current = start + ((end - start) * ratio)
    return weighted_current, 100.0


class ReviewProgressRecorder:
    """MCP progress를 review별 단조 증가 이벤트로 DB에 기록한다."""

    def __init__(self, database: Database, review_id: str) -> None:
        self._database = database
        self._review_id = review_id

    async def __call__(
        self,
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        with self._database.session() as db_session:
            for _attempt in range(2):
                repository = SqlAlchemyReviewRepository(db_session)
                review = repository.get(self._review_id)
                if review is None or review.state is not ReviewState.REVIEWING:
                    return
                previous = review.progress or {}
                stage, display_message = _progress_message(
                    message,
                    str(previous.get("stage", "PREPARE")),
                )
                weighted_current, weighted_total = _weighted_progress(
                    stage,
                    progress,
                    total,
                )
                if not review.record_progress(
                    stage=stage,
                    current=weighted_current,
                    total=weighted_total,
                    message=display_message,
                ):
                    return
                try:
                    repository.save(review)
                    db_session.commit()
                    return
                except ConcurrentReviewUpdateError:
                    db_session.rollback()
                    db_session.expire_all()


async def _call_review_tool(
    runtime: WorkShieldMCPRuntime,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
    progress_callback: ReviewProgressRecorder,
) -> dict[str, Any]:
    """실제 MCP session을 우선 사용하고 테스트 runtime은 tool 호출로 대체한다."""
    session = getattr(runtime, "session", None)
    if session is not None:
        result = await session.call_tool(
            "review_contract_candidates",
            payload,
            read_timeout_seconds=timedelta(seconds=timeout_seconds),
            progress_callback=progress_callback,
        )
        return _tool_payload(result)

    tool = next(
        candidate
        for candidate in runtime.tools
        if candidate.name == "review_contract_candidates"
    )
    result = await asyncio.wait_for(
        tool.ainvoke(payload),
        timeout=timeout_seconds,
    )
    return _tool_payload(result)


async def _invoke_review_tool(
    *,
    runtime: WorkShieldMCPRuntime,
    database: Database,
    storage: FileStorage,
    storage_key: str,
    file_name: str,
    contract_type: str,
    settings: Settings,
    review_id: str,
) -> dict[str, Any]:
    """선택된 MCP runtime에 transport별 계약서 입력을 전달한다."""
    if runtime.supports_file_path:
        with storage.local_path(storage_key) as local_path:
            arguments = {
                "contract_type": contract_type,
                "file_path": str(local_path),
            }
            return await _call_review_tool(
                runtime,
                arguments,
                timeout_seconds=settings.workshield_mcp_read_timeout,
                progress_callback=ReviewProgressRecorder(database, review_id),
            )

    with storage.open(storage_key) as stored_file:
        content = stored_file.read()
    arguments = {
        "contract_type": contract_type,
        "file_content": base64.b64encode(content).decode("ascii"),
        "file_name": file_name,
    }
    return await _call_review_tool(
        runtime,
        arguments,
        timeout_seconds=settings.workshield_mcp_read_timeout,
        progress_callback=ReviewProgressRecorder(database, review_id),
    )


async def execute_review(
    *,
    database: Database,
    storage: FileStorage,
    runtime: WorkShieldMCPRuntime,
    settings: Settings,
    review_id: str,
    policy: ReviewSessionPolicy = DEFAULT_REVIEW_SESSION_POLICY,
    runtime_factory: Callable[
        [], AsyncContextManager[WorkShieldMCPRuntime]
    ] | None = None,
) -> None:
    """검토를 수행하고 별도 DB session으로 최종 상태를 저장한다."""
    with database.session() as db_session:
        review_repository = SqlAlchemyReviewRepository(db_session)
        session_repository = SqlAlchemyReviewSessionRepository(db_session)
        review = review_repository.get(review_id)
        if review is None or review.state is not ReviewState.QUEUED:
            return
        review_session = session_repository.get(review.session_id)
        if review_session is None or review_session.storage_key is None:
            review.fail(
                {
                    "code": "SOURCE_FILE_UNAVAILABLE",
                    "retryable": False,
                    "next_action": "START_NEW_REVIEW",
                },
                at=datetime.now(UTC),
            )
            review_repository.save(review)
            db_session.commit()
            return
        review.start(at=datetime.now(UTC))
        review_repository.save(review)
        db_session.commit()
        storage_key = review_session.storage_key
        file_name = review_session.original_file_name
        contract_type = review.contract_type

    try:
        if runtime_factory is not None:
            async with runtime_factory() as execution_runtime:
                raw_result = await _invoke_review_tool(
                    runtime=execution_runtime,
                    storage=storage,
                    storage_key=storage_key,
                    file_name=file_name,
                    contract_type=contract_type,
                    settings=settings,
                    review_id=review_id,
                    database=database,
                )
                toxic_pattern_labels = await _toxic_pattern_label_snapshot(
                    execution_runtime,
                    timeout_seconds=settings.workshield_mcp_timeout,
                )
        else:
            raw_result = await _invoke_review_tool(
                runtime=runtime,
                database=database,
                storage=storage,
                storage_key=storage_key,
                file_name=file_name,
                contract_type=contract_type,
                settings=settings,
                review_id=review_id,
            )
            toxic_pattern_labels = await _toxic_pattern_label_snapshot(
                runtime,
                timeout_seconds=settings.workshield_mcp_timeout,
            )
        result_payload = normalize_review_result(
            raw_result,
            review_id=review_id,
            toxic_pattern_labels=toxic_pattern_labels,
        )
        status = _mcp_status(result_payload)
        error = None
        if status is not MCPReviewStatus.OK:
            retryable = status in {
                MCPReviewStatus.CORPUS_UNAVAILABLE,
                MCPReviewStatus.PIPELINE_ERROR,
            }
            error = {
                "code": status.value,
                "retryable": retryable,
                "next_action": "RETRY_REVIEW" if retryable else "CONTACT_SUPPORT",
            }
    except asyncio.CancelledError:
        return
    except (asyncio.TimeoutError, TimeoutError):
        status = None
        result_payload = None
        error = {
            "code": "MCP_TIMEOUT",
            "retryable": True,
            "next_action": "RETRY_REVIEW",
        }
    except InvalidMCPReviewResultError:
        status = None
        result_payload = None
        error = {
            "code": "MCP_RESPONSE_INVALID",
            "retryable": False,
            "next_action": "CONTACT_SUPPORT",
        }
    except Exception:
        logger.exception("MCP 검토 실패: review_id=%s", review_id)
        status = None
        result_payload = None
        error = {
            "code": "PIPELINE_ERROR",
            "retryable": True,
            "next_action": "RETRY_REVIEW",
        }

    with database.session() as db_session:
        repository = SqlAlchemyReviewRepository(db_session)
        session_repository = SqlAlchemyReviewSessionRepository(db_session)
        review = repository.get(review_id)
        if review is None or review.state is not ReviewState.REVIEWING:
            return
        completed_at = datetime.now(UTC)
        if status is MCPReviewStatus.OK and result_payload is not None:
            review.complete(status, result_payload, at=completed_at)
        else:
            review.fail(error or {"code": "PIPELINE_ERROR"}, status, at=completed_at)
        try:
            repository.save(review)
        except ConcurrentReviewUpdateError:
            db_session.rollback()
            return
        resume_ttl_after_review(
            db_session,
            review,
            ttl_seconds=policy.session_ttl_seconds,
        )
        storage_key_to_delete = None
        if (
            review.state is ReviewState.FAILED
            and review.error
            and not review.error.get("retryable", False)
        ):
            review_session = session_repository.get(review.session_id)
            if review_session is not None and review_session.storage_key is not None:
                storage_key_to_delete = review_session.storage_key
                review_session.storage_key = None
                session_repository.save(review_session)
        db_session.commit()
    if storage_key_to_delete is not None:
        storage.delete(storage_key_to_delete)
