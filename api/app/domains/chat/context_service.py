"""후속 질문에 필요한 최소 대화 상태를 대화 원문 없이 보관한다."""

import secrets
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db.models import ChatContextRow


class ChatContextTargetKind(StrEnum):
    """후속 질문이 이어받을 직전 답변 대상의 종류."""

    SINGLE_CLAUSE = "SINGLE_CLAUSE"
    RESULT_GROUP = "RESULT_GROUP"
    MISSING_STANDARD_CLAUSES = "MISSING_STANDARD_CLAUSES"
    REVIEW_ALL = "REVIEW_ALL"


class ChatContextState(BaseModel):
    """서버가 발급한 다음 질문용 범위 정보."""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(description="직전 답변에서 확정한 질문 유형 코드")
    target_kind: ChatContextTargetKind = Field(
        default=ChatContextTargetKind.REVIEW_ALL,
        description="후속 질문이 이어받을 직전 답변 대상 종류",
    )
    selected_clause_ids: list[str] = Field(
        default_factory=list,
        description="대상 사용자 조항 ID 목록. 결과군 전체를 저장할 때도 원래 순서를 유지한다.",
    )
    result_codes: list[str] = Field(
        default_factory=list,
        description="결과군 대상일 때 적용할 검토 상태 코드 목록(EXTRA, NO_MATCH 등)",
    )
    missing_standard_clause_ids: list[str] = Field(
        default_factory=list,
        description="대상 표준조항 누락 후보 ID 목록. 사용자 조항 ID와 섞지 않는다.",
    )
    answer_scope: str = Field(
        default="review",
        description="호환성을 위한 답변 범위 표시. 대상 선택은 target_kind를 우선한다.",
    )
    next_segment_offset: int | None = Field(
        default=None,
        ge=0,
        description="분할 답변을 이어 시작할 다음 묶음 오프셋",
    )


def issue_chat_context(
    db_session: Session,
    *,
    session_id: str,
    review_id: str,
    state: ChatContextState,
    expires_at: datetime,
) -> str:
    """예측 불가능한 토큰으로 최소 상태를 저장한다."""
    token = f"ctx_{secrets.token_urlsafe(24)}"
    db_session.add(
        ChatContextRow(
            id=token,
            session_id=session_id,
            review_id=review_id,
            state=state.model_dump(mode="json"),
            created_at=datetime.now(UTC),
            expires_at=expires_at,
        )
    )
    return token


def load_chat_context(
    db_session: Session,
    *,
    token: str | None,
    session_id: str,
    review_id: str,
    now: datetime | None = None,
) -> ChatContextState | None:
    """현재 소유 검토에 결합된 미만료 상태만 반환한다."""
    if not token:
        return None
    current = now or datetime.now(UTC)
    row = db_session.scalar(
        select(ChatContextRow).where(
            ChatContextRow.id == token,
            ChatContextRow.session_id == session_id,
            ChatContextRow.review_id == review_id,
        )
    )
    if row is None:
        return None
    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
    if expires_at <= current:
        db_session.delete(row)
        return None
    try:
        return ChatContextState.model_validate(row.state)
    except ValueError:
        return None


def delete_expired_chat_contexts(db_session: Session, now: datetime) -> int:
    """만료한 최소 대화 상태를 일괄 폐기한다."""
    result = db_session.execute(delete(ChatContextRow).where(ChatContextRow.expires_at <= now))
    return int(result.rowcount or 0)
