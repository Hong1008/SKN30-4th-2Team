"""검토 범위 질의응답 (Chat) API."""

from fastapi import APIRouter, Header, Request

from app.config import SettingsDep
from app.core.access_control.dependencies import OwnedReviewDep
from app.core.common.responses import (
    ApiResponse,
    COMMON_ERROR_RESPONSES,
    success_response,
)
from app.core.db.dependencies import DbSessionDep
from app.core.idempotency.service import (
    find_replay,
    idempotency_guard,
    request_fingerprint,
    require_idempotency_key,
    save_response,
)
from app.core.llm.dependencies import ChatModelDep
from app.core.llm.mcp.dependencies import WorkShieldMCPRuntimeDep
from app.domains.chat.schemas import ChatRequest, ChatResponse
from app.domains.chat.service import answer_review_question

router = APIRouter(
    prefix="/reviews",
    tags=["reviews"],
    responses=COMMON_ERROR_RESPONSES,
)


@router.post(
    "/{review_id}/chat/messages",
    response_model=ApiResponse[ChatResponse],
)
async def chat_message(
    request: Request,
    owned: OwnedReviewDep,
    payload: ChatRequest,
    db_session: DbSessionDep,
    runtime: WorkShieldMCPRuntimeDep,
    model: ChatModelDep,
    settings: SettingsDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """대화 본문을 별도 영구 이력으로 남기지 않는 검토 범위 질의응답."""
    key = require_idempotency_key(idempotency_key)
    fingerprint = request_fingerprint(
        {
            "review_id": owned.id,
            "payload": payload.model_dump(mode="json"),
        }
    )
    async with idempotency_guard(
        scope="reviews.chat",
        session_id=owned.session_id,
        idempotency_key=key,
    ):
        replay = find_replay(
            db_session,
            scope="reviews.chat",
            session_id=owned.session_id,
            idempotency_key=key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return success_response(request, ChatResponse.model_validate(replay))
        data = await answer_review_question(
            owned,
            payload,
            runtime=runtime,
            model=model,
            settings=settings,
        )
        raced_replay = save_response(
            db_session,
            scope="reviews.chat",
            session_id=owned.session_id,
            idempotency_key=key,
            fingerprint=fingerprint,
            response_snapshot=data.model_dump(mode="json"),
            ttl_seconds=settings.session_ttl_seconds,
        )
        if raced_replay is not None:
            data = ChatResponse.model_validate(raced_replay)
        else:
            db_session.commit()
        return success_response(request, data)
