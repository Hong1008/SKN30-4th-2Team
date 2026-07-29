"""검토 범위 질의응답 (Chat) API."""

from fastapi import APIRouter

from app.core.access_control.dependencies import OwnedReviewDep
from app.core.common.responses import (
    ApiResponse,
    COMMON_ERROR_RESPONSES,
)
from app.core.idempotency import IdempotencyContextDep, idempotent
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
@idempotent(
    scope="reviews.chat",
    response_model=ChatResponse,
    get_session_id=lambda *, owned, **kw: owned.session_id,
    get_fingerprint_payload=lambda *, owned, payload, **kw: {
        "review_id": owned.id,
        "payload": payload.model_dump(mode="json"),
    },
    use_guard=True,
)
async def chat_message(
    owned: OwnedReviewDep,
    payload: ChatRequest,
    runtime: WorkShieldMCPRuntimeDep,
    model: ChatModelDep,
    idem_ctx: IdempotencyContextDep,
):
    """대화 본문을 별도 영구 이력으로 남기지 않는 검토 범위 질의응답."""
    return await answer_review_question(
        owned,
        payload,
        runtime=runtime,
        model=model,
        settings=idem_ctx.settings,
    )
