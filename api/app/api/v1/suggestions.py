"""검토 협의 초안 생성 (Suggestions) API."""

from fastapi import APIRouter

from app.core.access_control.dependencies import OwnedReviewDep
from app.core.common.responses import (
    ApiResponse,
    COMMON_ERROR_RESPONSES,
)
from app.core.idempotency import IdempotencyContextDep, idempotent
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
@idempotent(
    scope="reviews.suggestions",
    response_model=SuggestionResponse,
    get_session_id=lambda *, owned, **kw: owned.session_id,
    get_fingerprint_payload=lambda *, owned, payload, **kw: {
        "review_id": owned.id,
        "payload": payload.model_dump(mode="json"),
    },
    use_guard=True,
)
async def create_suggestion(
    owned: OwnedReviewDep,
    payload: SuggestionRequest,
    runtime: WorkShieldMCPRuntimeDep,
    model: ChatModelDep,
    idem_ctx: IdempotencyContextDep,
):
    """검증된 단일 사용자·표준조항과 grounding으로 협의 초안을 생성한다."""
    return await generate_suggestion(
        owned,
        payload,
        runtime=runtime,
        model=model,
        settings=idem_ctx.settings,
    )
