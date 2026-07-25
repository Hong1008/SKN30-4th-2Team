"""WorkShield MCP 범위 판별 응답을 제품 계약으로 정규화한다."""

from __future__ import annotations

from typing import Any

from app.core.common.errors import ExternalServiceError
from app.domains.review_sessions.domain import ScopeStatus


def _invalid_response() -> ExternalServiceError:
    return ExternalServiceError(
        code="MCP_RESPONSE_INVALID",
        message="검토 서비스의 범위 판별 응답이 올바르지 않습니다.",
        next_action="CONTACT_SUPPORT",
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid_response()
    normalized = value.strip()
    return normalized or None


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _invalid_response()
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise _invalid_response()
        stripped = item.strip()
        if stripped:
            normalized.append(stripped)
    return normalized


def normalize_scope_result(payload: dict[str, Any]) -> dict[str, Any]:
    """누락 가능한 필드에는 기본값을 적용하고 잘못된 필드는 거부한다."""
    raw_status = payload.get("status", payload.get("scope_status"))
    if not isinstance(raw_status, str):
        raise _invalid_response()
    try:
        status = ScopeStatus(raw_status.upper())
    except ValueError as error:
        raise _invalid_response() from error

    raw_candidates = payload.get("candidates")
    if raw_candidates is None:
        raw_candidates = []
    if not isinstance(raw_candidates, list):
        raise _invalid_response()
    candidates: list[dict[str, Any]] = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            raise _invalid_response()
        contract_type = _optional_string(item.get("contract_type"))
        score = item.get("score")
        if (
            contract_type is None
            or not isinstance(score, int)
            or isinstance(score, bool)
        ):
            raise _invalid_response()
        candidates.append({"contract_type": contract_type, "score": score})

    matched_clause_count = payload.get("matched_clause_count")
    if matched_clause_count is None:
        matched_clause_count = 0
    if (
        not isinstance(matched_clause_count, int)
        or isinstance(matched_clause_count, bool)
        or matched_clause_count < 0
    ):
        raise _invalid_response()

    return {
        "status": status.value,
        "suggested_contract_type": _optional_string(
            payload.get("suggested_contract_type")
        ),
        "candidates": candidates,
        "matched_clause_count": matched_clause_count,
        "exclusion_markers": _string_list(payload.get("exclusion_markers")),
        "message": _optional_string(payload.get("message")),
    }
