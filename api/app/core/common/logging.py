"""민감한 본문 없이 운영 이벤트를 기록하는 최소 로그 도구."""

import hashlib
import logging


logger = logging.getLogger("uvicorn.error")


def hash_session_id(session_id: str) -> str:
    """원본 세션 ID 대신 로그 추적용 단방향 해시를 반환한다."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def _safe_token(value: object) -> str:
    """로그 한 줄 구조를 깨뜨리는 공백과 개행을 제거한다."""
    return "_".join(str(value).split())


def log_event(
    *,
    event: str,
    request_id: str,
    session_id: str | None = None,
    review_id: str | None = None,
    state: str | int | None = None,
    duration_ms: float | None = None,
    level: int = logging.INFO,
) -> None:
    """허용된 비식별 필드만 key=value 형식으로 기록한다."""
    fields: list[tuple[str, object]] = [
        ("event", event),
        ("request_id", request_id),
    ]
    if session_id is not None:
        fields.append(("session_id_hash", hash_session_id(session_id)))
    if review_id is not None:
        fields.append(("review_id", review_id))
    if state is not None:
        fields.append(("state", state))
    if duration_ms is not None:
        fields.append(("duration_ms", duration_ms))

    message = " ".join(
        f"{key}={_safe_token(value)}"
        for key, value in fields
    )
    logger.log(level, message)
