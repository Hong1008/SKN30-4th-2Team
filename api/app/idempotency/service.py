"""공통 Idempotency-Key 검증과 응답 스냅샷 저장."""

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.errors import AppValidationError, ConflictError
from app.db.models import IdempotencyRecordRow


@dataclass(slots=True)
class _GuardEntry:
    """단일 프로세스 내 동일 멱등 요청을 직렬화하는 잠금 항목."""

    lock: asyncio.Lock
    users: int = 0


_guards: dict[tuple[str, str, str], _GuardEntry] = {}


@asynccontextmanager
async def idempotency_guard(
    *,
    scope: str,
    session_id: str,
    idempotency_key: str,
) -> AsyncIterator[None]:
    """동일 프로세스의 같은 멱등 키 외부 호출이 중복되지 않게 직렬화한다.

    다중 프로세스 경쟁은 DB unique 제약과 ``save_response``의 승자 재조회로
    처리한다.
    """
    guard_key = (scope, session_id, idempotency_key)
    entry = _guards.get(guard_key)
    if entry is None:
        entry = _GuardEntry(lock=asyncio.Lock())
        _guards[guard_key] = entry
    entry.users += 1
    acquired = False
    try:
        await entry.lock.acquire()
        acquired = True
        yield
    finally:
        if acquired:
            entry.lock.release()
        entry.users -= 1
        if entry.users == 0 and _guards.get(guard_key) is entry:
            _guards.pop(guard_key, None)


def request_fingerprint(payload: Any) -> str:
    """요청 의미를 안정적인 JSON으로 직렬화해 SHA-256 지문을 만든다."""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def internal_operation_key(scope: str, idempotency_key: str) -> str:
    """legacy review row의 scope 없는 unique 키 충돌을 피할 내부 키를 만든다."""
    digest = hashlib.sha256(f"{scope}\0{idempotency_key}".encode("utf-8")).hexdigest()
    return f"op_{digest}"


def require_idempotency_key(value: str | None) -> str:
    """필수 멱등 키의 길이와 공백 값을 검증한다."""
    key = value.strip() if value else ""
    if not key:
        raise AppValidationError(
            code="REQUIRED_VALUE_MISSING",
            message="Idempotency-Key 헤더가 필요합니다.",
            field="Idempotency-Key",
        )
    if len(key) > 128:
        raise AppValidationError(
            code="VALIDATION_ERROR",
            message="Idempotency-Key는 128자 이하여야 합니다.",
            field="Idempotency-Key",
        )
    return key


def find_replay(
    db_session: Session,
    *,
    scope: str,
    session_id: str,
    idempotency_key: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    """동일 요청이면 저장 응답을 반환하고 다른 요청이면 충돌시킨다."""
    now = datetime.now(UTC)
    statement = select(IdempotencyRecordRow).where(
        IdempotencyRecordRow.scope == scope,
        IdempotencyRecordRow.session_id == session_id,
        IdempotencyRecordRow.idempotency_key == idempotency_key,
    )
    record = db_session.scalar(statement)
    if record is None:
        return None
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if now >= expires_at:
        db_session.delete(record)
        db_session.flush()
        return None
    if record.request_fingerprint != fingerprint:
        raise ConflictError(
            code="IDEMPOTENCY_KEY_REUSED",
            message="동일한 Idempotency-Key가 다른 요청에 사용되었습니다.",
            field="Idempotency-Key",
        )
    return dict(record.response_snapshot)


def save_response(
    db_session: Session,
    *,
    scope: str,
    session_id: str,
    idempotency_key: str,
    fingerprint: str,
    response_snapshot: dict[str, Any],
    ttl_seconds: int,
) -> dict[str, Any] | None:
    """응답을 저장하고 unique 경쟁에서는 먼저 저장된 응답을 반환한다."""
    now = datetime.now(UTC)
    db_session.add(
        IdempotencyRecordRow(
            id=f"idem_{uuid.uuid4().hex}",
            scope=scope,
            session_id=session_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            response_snapshot=response_snapshot,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
    )
    try:
        db_session.flush()
    except IntegrityError as error:
        db_session.rollback()
        replay = find_replay(
            db_session,
            scope=scope,
            session_id=session_id,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is None:
            raise error
        return replay
    return None


def delete_expired_records(db_session: Session, now: datetime) -> int:
    """만료된 멱등 스냅샷을 반복 호출해도 안전하게 삭제한다."""
    result = db_session.execute(
        delete(IdempotencyRecordRow).where(
            IdempotencyRecordRow.expires_at <= now,
        )
    )
    return int(result.rowcount or 0)
