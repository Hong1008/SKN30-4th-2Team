"""검토 협의 초안 생성 (Suggestions) API."""

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
from app.domains.suggestions.schemas import SuggestionRequest, SuggestionResponse
from app.domains.suggestions.service import generate_suggestion

router = APIRouter(
    prefix="/reviews",
    tags=["reviews"],
    responses=COMMON_ERROR_RESPONSES,
)


@router.post(
    "/{review_id}/suggestions",
    response_model=ApiResponse[SuggestionResponse],
)
async def create_suggestion(
    request: Request,
    owned: OwnedReviewDep,
    payload: SuggestionRequest,
    db_session: DbSessionDep,
    runtime: WorkShieldMCPRuntimeDep,
    model: ChatModelDep,
    settings: SettingsDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """검증된 단일 사용자·표준조항과 grounding으로 협의 초안을 생성한다."""
    key = require_idempotency_key(idempotency_key)
    fingerprint = request_fingerprint(
        {
            "review_id": owned.id,
            "payload": payload.model_dump(mode="json"),
        }
    )
    async with idempotency_guard(
        scope="reviews.suggestions",
        session_id=owned.session_id,
        idempotency_key=key,
    ):
        replay = find_replay(
            db_session,
            scope="reviews.suggestions",
            session_id=owned.session_id,
            idempotency_key=key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return success_response(
                request,
                SuggestionResponse.model_validate(replay),
            )
        data = await generate_suggestion(
            owned,
            payload,
            runtime=runtime,
            model=model,
            settings=settings,
        )
        raced_replay = save_response(
            db_session,
            scope="reviews.suggestions",
            session_id=owned.session_id,
            idempotency_key=key,
            fingerprint=fingerprint,
            response_snapshot=data.model_dump(mode="json"),
            ttl_seconds=settings.session_ttl_seconds,
        )
        if raced_replay is not None:
            data = SuggestionResponse.model_validate(raced_replay)
        else:
            db_session.commit()
        return success_response(request, data)
