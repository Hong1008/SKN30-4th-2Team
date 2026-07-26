"""검토 접수·상태·결과·진행·재시도·취소 API."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Header, Request
from sse_starlette.sse import EventSourceResponse

from app.config import SettingsDep
from app.core.access_control.dependencies import (
    OwnedReviewDep,
    SessionCookie,
    resolve_owned_review,
    resolve_owned_session,
)
from app.core.common.errors import ConflictError
from app.core.common.responses import (
    ApiErrorResponse,
    ApiResponse,
    COMMON_ERROR_RESPONSES,
    success_response,
)
from app.core.db.dependencies import DatabaseDep, DbSessionDep
from app.core.idempotency import IdempotencyContextDep, idempotent
from app.core.idempotency.service import (
    find_replay,
    idempotency_guard,
    internal_operation_key,
    request_fingerprint,
    require_idempotency_key,
    save_response,
)
from app.core.llm.mcp.dependencies import WorkShieldMCPRuntimeDep
from app.core.storage.dependencies import FileStorageDep
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.domains.reviews.domain import ReviewState
from app.domains.reviews.presentation import present_review_results
from app.domains.reviews.repository import SqlAlchemyReviewRepository
from app.domains.reviews.repository import ConcurrentReviewUpdateError
from app.domains.reviews.runner import execute_review
from app.domains.reviews.schemas import (
    ReviewCancelResponse,
    ReviewCreateRequest,
    ReviewCreateResponse,
    ReviewSseEvent,
    ReviewResponse,
    ReviewResultsResponse,
)
from app.domains.reviews.service import create_review, retry_review

router = APIRouter(
    prefix="/reviews",
    tags=["reviews"],
    responses=COMMON_ERROR_RESPONSES,
)


def _schedule_review(
    request: Request,
    *,
    database,
    review_id: str,
    storage,
    runtime,
    settings,
) -> None:
    """검토를 앱 수명주기와 함께 추적하는 백그라운드 작업으로 예약한다."""
    task = asyncio.create_task(
        execute_review(
            database=database,
            storage=storage,
            runtime=runtime,
            settings=settings,
            review_id=review_id,
        )
    )
    tasks = getattr(request.app.state, "review_tasks", {})
    tasks[review_id] = task
    request.app.state.review_tasks = tasks
    task.add_done_callback(lambda _task: tasks.pop(review_id, None))


def _response(entity: object) -> ReviewResponse:
    return ReviewResponse(
        review_id=entity.id,
        session_id=entity.session_id,
        review_state=entity.state,
        mcp_review_status=entity.mcp_review_status,
        progress=entity.progress,
        result=entity.result,
        error=entity.error,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
        expires_at=entity.expires_at,
    )


@router.post(
    "",
    status_code=202,
    response_model=ApiResponse[ReviewCreateResponse],
)
async def start_review(
    request: Request,
    payload: ReviewCreateRequest,
    db_session: DbSessionDep,
    database: DatabaseDep,
    settings: SettingsDep,
    access_token: SessionCookie = None,
    runtime: WorkShieldMCPRuntimeDep = None,
    storage: FileStorageDep = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Cookie 소유 세션의 검토를 fingerprint 기준으로 멱등 접수한다."""
    key = require_idempotency_key(idempotency_key)
    review_session = resolve_owned_session(
        payload.session_id,
        access_token,
        db_session,
    )
    async with idempotency_guard(
        scope="reviews.create",
        session_id=review_session.id,
        idempotency_key=key,
    ):
        fingerprint = request_fingerprint(payload.model_dump(mode="json"))
        replay = find_replay(
            db_session,
            scope="reviews.create",
            session_id=review_session.id,
            idempotency_key=key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return success_response(
                request,
                ReviewCreateResponse.model_validate(replay),
            )
        entity = create_review(
            db_session,
            review_session,
            idempotency_key=internal_operation_key("reviews.create", key),
            settings=settings,
        )
        response_data = ReviewCreateResponse(
            review_id=entity.id,
            review_state=entity.state.value,
            session_id=entity.session_id,
        )
        raced_replay = save_response(
            db_session,
            scope="reviews.create",
            session_id=review_session.id,
            idempotency_key=key,
            fingerprint=fingerprint,
            response_snapshot=response_data.model_dump(mode="json"),
            ttl_seconds=settings.session_ttl_seconds,
        )
        if raced_replay is not None:
            return success_response(
                request,
                ReviewCreateResponse.model_validate(raced_replay),
            )
        db_session.commit()
        _schedule_review(
            request,
            database=database,
            review_id=entity.id,
            storage=storage,
            runtime=runtime,
            settings=settings,
        )
        return success_response(request, response_data)


@router.get(
    "/{review_id}/results",
    response_model=ApiResponse[ReviewResultsResponse],
    response_model_exclude_none=True,
    responses={
        409: {
            "model": ApiErrorResponse,
            "description": "검토가 아직 완료되지 않음 (REVIEW_NOT_COMPLETED)",
        },
    },
)
def get_results(request: Request, owned: OwnedReviewDep):
    if owned.state is not ReviewState.COMPLETED:
        raise ConflictError(
            code="REVIEW_NOT_COMPLETED",
            message="검토가 아직 완료되지 않았습니다.",
        )
    return success_response(
        request,
        present_review_results(
            owned,
            metadata_cache=getattr(request.app.state, "metadata_cache", None),
        ),
    )


@router.get(
    "/{review_id}/events",
    response_class=EventSourceResponse,
    responses={
        200: {
            "model": ReviewSseEvent,
            "description": (
                "text/event-stream. event는 progress, completed, failed 중 하나이고, "
                "data는 ReviewSseEvent JSON이다. id는 data.sequence와 같다."
            ),
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/ReviewSseEvent"}
                }
            },
        },
    },
)
async def review_events(
    request: Request,
    owned: OwnedReviewDep,
    database: DatabaseDep,
    access_token: SessionCookie = None,
):
    """저장된 MCP progress를 단조 sequence의 SSE로 전달한다.

    재연결 요청의 ``Last-Event-ID``가 숫자이면 해당 sequence 이하의 progress는
    다시 보내지 않는다. terminal 상태는 completed 또는 failed 이벤트를 한 번
    전송한 뒤 스트림을 종료한다.
    """

    async def stream() -> AsyncIterator[dict[str, str]]:
        current = owned
        last_event_id = request.headers.get("Last-Event-ID")
        last_sequence = int(last_event_id) if (last_event_id or "").isdigit() else -1
        while True:
            sequence = int((current.progress or {}).get("sequence", 0))
            if current.state is ReviewState.COMPLETED:
                event_name = "completed"
            elif current.state in {
                ReviewState.FAILED,
                ReviewState.EXPIRED,
                ReviewState.CANCELLED,
            }:
                event_name = "failed"
            else:
                event_name = "progress"
            if sequence > last_sequence or event_name in {"completed", "failed"}:
                progress = current.progress or {}
                event_data = {
                    "review_id": current.id,
                    "sequence": sequence,
                    "review_state": current.state.value,
                    "stage": progress.get("stage"),
                    "current": progress.get("current"),
                    "total": progress.get("total"),
                    "percent": progress.get("percent"),
                    "message": progress.get("message"),
                }
                if event_name in {"completed", "failed"}:
                    event_data.update(
                        {
                            "mcp_review_status": (
                                current.mcp_review_status.value
                                if current.mcp_review_status
                                else None
                            ),
                            "error": current.error,
                        }
                    )
                yield {
                    "event": event_name,
                    "id": str(sequence),
                    "data": json.dumps(
                        event_data,
                        ensure_ascii=False,
                    ),
                }
                last_sequence = sequence
            if event_name in {"completed", "failed"}:
                return
            await asyncio.sleep(1)
            if await request.is_disconnected():
                return
            with database.session() as db_session:
                current = resolve_owned_review(
                    current.id,
                    access_token,
                    db_session,
                )

    return EventSourceResponse(stream())


@router.get("/{review_id}", response_model=ApiResponse[ReviewResponse])
def get_review(request: Request, owned: OwnedReviewDep):
    return success_response(request, _response(owned))


@router.post(
    "/{review_id}/retry",
    status_code=202,
    response_model=ApiResponse[ReviewCreateResponse],
)
@idempotent(
    scope="reviews.retry",
    response_model=ReviewCreateResponse,
    get_session_id=lambda *, owned, **kw: owned.session_id,
    get_fingerprint_payload=lambda *, owned, **kw: {"review_id": owned.id},
    post_commit=lambda *, database, response_data, storage, runtime, idem_ctx, **kw: _schedule_review(
        idem_ctx.request,
        database=database,
        review_id=response_data.review_id,
        storage=storage,
        runtime=runtime,
        settings=idem_ctx.settings,
    ),
)
async def retry(
    owned: OwnedReviewDep,
    database: DatabaseDep,
    idem_ctx: IdempotencyContextDep,
    runtime: WorkShieldMCPRuntimeDep = None,
    storage: FileStorageDep = None,
):
    entity = retry_review(
        idem_ctx.db_session,
        owned,
        idempotency_key=internal_operation_key(
            "reviews.retry", idem_ctx.request.state.idempotency_key
        ),
        settings=idem_ctx.settings,
    )
    return ReviewCreateResponse(
        review_id=entity.id,
        review_state=entity.state.value,
        session_id=entity.session_id,
        retry_of=entity.retry_of_review_id,
    )



@router.delete(
    "/{review_id}",
    response_model=ApiResponse[ReviewCancelResponse],
)
async def cancel_review(
    request: Request,
    owned: OwnedReviewDep,
    db_session: DbSessionDep,
    storage: FileStorageDep,
):
    """작업을 취소 표시하고 결과·원본 파일을 멱등하게 폐기한다."""
    task = getattr(request.app.state, "review_tasks", {}).pop(owned.id, None)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    repository = SqlAlchemyReviewRepository(db_session)
    current = owned
    for _attempt in range(3):
        db_session.expire_all()
        current = repository.get(owned.id)
        if current is None:
            current = owned
        if current.state is ReviewState.CANCELLED:
            break
        current.cancel(at=datetime.now(UTC))
        try:
            repository.save(current)
            db_session.commit()
            break
        except ConcurrentReviewUpdateError:
            db_session.rollback()
    else:
        raise ConflictError(
            code="REVIEW_STATE_CONFLICT",
            message="검토 상태가 동시에 변경되어 취소하지 못했습니다.",
        )

    session_repository = SqlAlchemyReviewSessionRepository(db_session)
    review_session = session_repository.get(current.session_id)
    deleted = False
    storage_key_to_delete = None
    if review_session is not None and review_session.storage_key is not None:
        storage_key_to_delete = review_session.storage_key
        review_session.storage_key = None
        review_session.scope_result = None
        session_repository.save(review_session)
        deleted = True
    db_session.commit()
    if storage_key_to_delete is not None:
        storage.delete(storage_key_to_delete)
    return success_response(
        request,
        ReviewCancelResponse(
            review_id=current.id,
            review_state=current.state.value,
            deleted=deleted,
        ),
    )
