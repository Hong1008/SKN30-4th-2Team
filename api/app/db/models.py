"""검토 세션과 검토 결과를 임시 보관하는 SQLAlchemy ORM Row."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReviewSessionRow(Base):
    """파일 업로드부터 계약 유형 확정까지의 세션 Row."""

    __tablename__ = "review_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    access_token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    state: Mapped[str] = mapped_column(String(64))
    scope_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    suggested_contract_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    selected_contract_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    selection_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    out_of_scope_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    original_file_name: Mapped[str] = mapped_column(String(255))
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )


class ReviewRow(Base):
    """MCP 검토 상태와 정규화 결과를 보관하는 Row."""

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_reviews_session_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("review_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    retry_of_review_id: Mapped[str | None] = mapped_column(
        ForeignKey("reviews.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(32))
    mcp_review_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    contract_type: Mapped[str] = mapped_column(String(64))
    progress: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )


class IdempotencyRecordRow(Base):
    """API 멱등 키와 요청 지문, 재사용할 응답 스냅샷을 보관한다."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "session_id",
            "idempotency_key",
            name="uq_idempotency_scope_session_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(96))
    session_id: Mapped[str] = mapped_column(
        ForeignKey("review_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    response_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
