"""검토 범위 질의응답 (Chat) API."""

import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header
from sse_starlette.sse import EventSourceResponse

from app.core.access_control.dependencies import OwnedReviewDep
from app.core.common.responses import (
    ApiResponse,
    COMMON_ERROR_RESPONSES,
)
from app.core.db.dependencies import DbSessionDep
from app.core.idempotency import IdempotencyContextDep, idempotent
from app.core.idempotency.service import require_idempotency_key
from app.config import SettingsDep
from app.core.llm.dependencies import ChatModelDep, RouterModelDep
from app.core.llm.mcp.dependencies import WorkShieldMCPRuntimeDep
from app.domains.chat.schemas import (
    ChatRequest,
    ChatResponse,
    ChatStreamError,
    ChatStreamCompletedEvent,
    ChatStreamContinuation,
    ChatStreamDeltaEvent,
    ChatStreamFailedEvent,
    ChatStreamProgressEvent,
    ChatStreamSegment,
    ChatStreamSegmentCompleteEvent,
    ChatStreamStage,
)
from app.domains.chat.service import (
    answer_plan_context,
    answer_review_question,
    stream_review_answer,
)
from app.domains.chat.context_service import (
    ChatContextState,
    issue_chat_context,
    load_chat_context,
)

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
    db_session: DbSessionDep,
    runtime: WorkShieldMCPRuntimeDep,
    router_model: RouterModelDep,
    model: ChatModelDep,
    idem_ctx: IdempotencyContextDep,
):
    """대화 본문을 별도 영구 이력으로 남기지 않는 검토 범위 질의응답."""
    payload, conversation_context = _apply_conversation_context(payload, owned, db_session)
    response = await answer_review_question(
        owned,
        payload,
        runtime=runtime,
        router_model=router_model,
        model=model,
        settings=idem_ctx.settings,
        conversation_context=conversation_context,
    )
    response.conversation_token = _issue_response_context(
        db_session=db_session,
        owned=owned,
        payload=payload,
        response=response,
        conversation_context=conversation_context,
    )
    return response


def _apply_conversation_context(
    payload: ChatRequest,
    owned,
    db_session: DbSessionDep,
) -> tuple[ChatRequest, ChatContextState | None]:
    """명시 대상이 없을 때만 검증된 원문 없는 직전 대상을 이어받는다."""
    if payload.focus_clause_id:
        return payload, None
    context = load_chat_context(
        db_session,
        token=payload.conversation_token,
        session_id=owned.session_id,
        review_id=owned.id,
    )
    return payload, context


def _issue_response_context(
    *,
    db_session: DbSessionDep,
    owned: OwnedReviewDep,
    payload: ChatRequest,
    response: ChatResponse,
    conversation_context: ChatContextState | None,
    next_segment_offset: int | None = None,
) -> str:
    """완료 답변의 의미 대상만 다음 질문용 토큰으로 저장한다."""
    state = ChatContextState.model_validate(
        answer_plan_context(
            owned,
            payload,
            response.question_category,
            conversation_context=conversation_context,
        )
    )
    if next_segment_offset is not None:
        state = state.model_copy(
            update={"next_segment_offset": next_segment_offset}
        )
    return issue_chat_context(
        db_session,
        session_id=owned.session_id,
        review_id=owned.id,
        state=state,
        expires_at=owned.expires_at,
    )


def _as_segment(value: object) -> ChatStreamSegment | None:
    """서비스의 dict/model 세그먼트 표현을 공개 DTO로 정규화한다."""
    if value is None:
        return None
    return (
        value
        if isinstance(value, ChatStreamSegment)
        else ChatStreamSegment.model_validate(value)
    )


def _as_continuation(value: object) -> ChatStreamContinuation | None:
    """서비스의 dict/model 이어보기 정보를 공개 DTO로 정규화한다."""
    if value is None:
        return None
    return (
        value
        if isinstance(value, ChatStreamContinuation)
        else ChatStreamContinuation.model_validate(value)
    )


def _completed_parts(data: object) -> tuple[ChatResponse, ChatStreamContinuation | None]:
    """기존 ChatResponse와 새 분할 완료 payload를 모두 받아들인다."""
    if isinstance(data, ChatResponse):
        return data, None
    if isinstance(data, tuple) and len(data) == 2 and isinstance(data[0], ChatResponse):
        return data[0], _as_continuation(data[1])
    payload = dict(data) if isinstance(data, dict) else {}
    response = payload.get("response")
    if not isinstance(response, ChatResponse):
        response = ChatResponse.model_validate(response)
    return response, _as_continuation(payload.get("continuation"))


@router.post(
    "/{review_id}/chat/messages/stream",
    response_class=EventSourceResponse,
    responses={
        200: {
            "model": ChatStreamProgressEvent,
            "description": (
                "text/event-stream. event는 progress, delta, segment_complete, "
                "completed, failed 중 하나이고 data는 각 ChatStream 이벤트 JSON이다. "
                "id는 data.sequence와 같다."
            ),
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
    },
)
async def chat_message_stream(
    owned: OwnedReviewDep,
    payload: ChatRequest,
    runtime: WorkShieldMCPRuntimeDep,
    router_model: RouterModelDep,
    model: ChatModelDep,
    settings: SettingsDep,
    db_session: DbSessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """검증된 검토 범위 답변을 SSE로 전달한다.

    기존 JSON 멱등성 데코레이터는 generator 소비 전에 응답을 저장하므로 여기에는
    적용하지 않는다. 스트림 전용 멱등성 조정자는 후속 변경에서 보강한다.
    """
    require_idempotency_key(idempotency_key)
    payload, conversation_context = _apply_conversation_context(payload, owned, db_session)
    stream_id = f"chat_{uuid.uuid4().hex}"

    async def stream() -> AsyncIterator[dict[str, str]]:
        sequence = 0
        try:
            async for event_name, data in stream_review_answer(
                owned,
                payload,
                runtime=runtime,
                router_model=router_model,
                model=model,
                settings=settings,
                conversation_context=conversation_context,
            ):
                if event_name == "progress":
                    event = ChatStreamProgressEvent(
                        stream_id=stream_id,
                        sequence=sequence,
                        stage=ChatStreamStage(data["stage"]),
                        message=str(data["message"]),
                        question_category=(
                            str(data["category"]) if data.get("category") else None
                        ),
                        context_used=conversation_context is not None,
                        segment=_as_segment(data.get("segment")),
                    )
                elif event_name == "delta":
                    delta = data if isinstance(data, dict) else {"text": data}
                    event = ChatStreamDeltaEvent(
                        stream_id=stream_id,
                        sequence=sequence,
                        text=str(delta["text"]),
                        segment=_as_segment(delta.get("segment")),
                    )
                elif event_name == "segment_complete":
                    segment_data = data if isinstance(data, dict) else {}
                    event = ChatStreamSegmentCompleteEvent(
                        stream_id=stream_id,
                        sequence=sequence,
                        segment=_as_segment(segment_data.get("segment")),
                        sources=segment_data.get("sources", []),
                    )
                elif event_name == "completed":
                    response, continuation = _completed_parts(data)
                    response.conversation_token = _issue_response_context(
                        db_session=db_session,
                        owned=owned,
                        payload=payload,
                        response=response,
                        conversation_context=conversation_context,
                        next_segment_offset=(
                            continuation.next_segment_offset if continuation else None
                        ),
                    )
                    db_session.commit()
                    event = ChatStreamCompletedEvent(
                        stream_id=stream_id,
                        sequence=sequence,
                        response=response,
                        continuation=continuation,
                    )
                elif event_name == "failed":
                    failed_data = data if isinstance(data, dict) else {}
                    error = failed_data.get("error", failed_data)
                    continuation = _as_continuation(failed_data.get("continuation"))
                    failure_token = None
                    if continuation:
                        failure_response = ChatResponse(
                            outcome="REFUSED",
                            answer=None,
                            refused=True,
                            limitations=[],
                            tool_status="NOT_REQUESTED",
                            disclaimer="",
                            question_category=(
                                str(failed_data["question_category"])
                                if failed_data.get("question_category")
                                else (
                                    conversation_context.category
                                    if conversation_context
                                    else None
                                )
                            ),
                        )
                        failure_token = _issue_response_context(
                            db_session=db_session,
                            owned=owned,
                            payload=payload,
                            response=failure_response,
                            conversation_context=conversation_context,
                            next_segment_offset=continuation.next_segment_offset,
                        )
                        db_session.commit()
                    event = ChatStreamFailedEvent(
                        stream_id=stream_id,
                        sequence=sequence,
                        error=(
                            error
                            if isinstance(error, ChatStreamError)
                            else ChatStreamError.model_validate(error)
                        ),
                        partial_answer_available=bool(
                            failed_data.get("partial_answer_available", False)
                        ),
                        continuation=continuation,
                        conversation_token=failure_token,
                    )
                else:
                    raise ValueError(f"지원하지 않는 chat stream 이벤트입니다: {event_name}")
                yield {
                    "event": event_name,
                    "id": str(sequence),
                    "data": event.model_dump_json(),
                }
                sequence += 1
        except Exception as error:
            failed = ChatStreamFailedEvent(
                stream_id=stream_id,
                sequence=sequence,
                error=ChatStreamError(
                    code=getattr(error, "code", "CHAT_STREAM_FAILED"),
                    message=getattr(error, "message", "답변 스트림을 생성하지 못했습니다."),
                    retryable=bool(getattr(error, "retryable", False)),
                    next_action=getattr(error, "next_action", None),
                ),
            )
            yield {"event": "failed", "id": str(sequence), "data": failed.model_dump_json()}

    return EventSourceResponse(
        stream(),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
