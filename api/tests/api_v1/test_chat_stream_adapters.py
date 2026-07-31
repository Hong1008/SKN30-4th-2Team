"""Chat route의 대화 상태·분할 SSE 어댑터 단위 테스트."""

from types import SimpleNamespace

from app.api.v1.chat import _apply_conversation_context, _completed_parts
from app.domains.chat.schemas import (
    ChatOutcome,
    ChatRequest,
    ChatResponse,
    ChatStreamContinuation,
)


def test_explicit_focus_clause_bypasses_previous_context() -> None:
    """현재 요청의 명시 조항은 이전 결과군을 절대 덮어쓰지 않는다."""
    payload, context = _apply_conversation_context(
        ChatRequest(
            message="제11조를 설명해 주세요.",
            focus_clause_id="uc_11",
            conversation_token="ctx_previous",
        ),
        SimpleNamespace(session_id="ses_1", id="rev_1"),
        None,
    )

    assert payload.focus_clause_id == "uc_11"
    assert context is None


def test_completed_parts_preserves_segment_continuation() -> None:
    """분할 생성 완료 payload의 이어보기 위치를 SSE 완료 이벤트까지 보존한다."""
    response = ChatResponse(
        outcome=ChatOutcome.ANSWERED,
        answer="첫 묶음 답변",
        refused=False,
        tool_status="NOT_REQUESTED",
        disclaimer="면책 문구",
        question_category="REVIEW_ANALYSIS",
    )

    completed, continuation = _completed_parts(
        (
            response,
            {"next_segment_offset": 3, "remaining_segments": 2},
        )
    )

    assert completed is response
    assert continuation == ChatStreamContinuation(
        next_segment_offset=3,
        remaining_segments=2,
    )
