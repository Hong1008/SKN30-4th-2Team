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
    request_id: str | None = None,
    session_id: str | None = None,
    review_id: str | None = None,
    category: str | None = None,
    state: str | int | None = None,
    reason: str | None = None,
    error_type: str | None = None,
    sources: list[str] | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    duration_ms: float | None = None,
    level: int = logging.INFO,
) -> None:
    """허용된 비식별 필드만 key=value 형식으로 기록한다."""
    fields: list[tuple[str, object]] = [("event", event)]
    if request_id is not None:
        fields.append(("request_id", request_id))
    if session_id is not None:
        fields.append(("session_id_hash", hash_session_id(session_id)))
    if review_id is not None:
        fields.append(("review_id", review_id))
    if category is not None:
        fields.append(("category", category))
    if state is not None:
        fields.append(("state", state))
    if reason is not None:
        fields.append(("reason", reason))
    if error_type is not None:
        fields.append(("error_type", error_type))
    if sources is not None:
        fields.append(("sources", ",".join(sources) if sources else "none"))
    if prompt_tokens is not None:
        fields.append(("prompt_tokens", prompt_tokens))
    if completion_tokens is not None:
        fields.append(("completion_tokens", completion_tokens))
    if total_tokens is not None:
        fields.append(("total_tokens", total_tokens))
    if duration_ms is not None:
        fields.append(("duration_ms", duration_ms))

    message = " ".join(f"{key}={_safe_token(value)}" for key, value in fields)
    logger.log(level, message)
