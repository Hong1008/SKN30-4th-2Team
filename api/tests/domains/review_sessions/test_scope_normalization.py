"""MCP 범위 판별 응답 정규화 규칙을 테스트한다."""

import pytest

from app.core.common.errors import ExternalServiceError
from app.domains.review_sessions.scope_normalization import normalize_scope_result


@pytest.mark.parametrize(
    "status",
    [
        "IN_SCOPE",
        "CONTRACT_TYPE_UNCERTAIN",
        "OUT_OF_SCOPE",
        "EMPTY_DOCUMENT",
    ],
)
def test_all_scope_statuses_are_normalized(status: str) -> None:
    result = normalize_scope_result({"status": status})

    assert result == {
        "status": status,
        "suggested_contract_type": None,
        "candidates": [],
        "matched_clause_count": 0,
        "exclusion_markers": [],
        "message": None,
    }


def test_nullable_optional_fields_are_normalized_without_score_conversion() -> None:
    result = normalize_scope_result(
        {
            "scope_status": "in_scope",
            "suggested_contract_type": " SW_FREELANCE ",
            "candidates": [
                {"contract_type": "SW_FREELANCE", "score": 82},
                {"contract_type": "SI_SUBCONTRACT", "score": 82},
            ],
            "matched_clause_count": None,
            "exclusion_markers": None,
            "message": None,
        }
    )

    assert result["status"] == "IN_SCOPE"
    assert result["candidates"] == [
        {"contract_type": "SW_FREELANCE", "score": 82},
        {"contract_type": "SI_SUBCONTRACT", "score": 82},
    ]
    assert result["matched_clause_count"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "UNKNOWN"},
        {"status": "IN_SCOPE", "candidates": "invalid"},
        {"status": "IN_SCOPE", "candidates": [{}]},
        {
            "status": "IN_SCOPE",
            "candidates": [{"contract_type": "SW_FREELANCE", "score": 0.82}],
        },
        {"status": "IN_SCOPE", "matched_clause_count": -1},
        {"status": "IN_SCOPE", "exclusion_markers": [1]},
    ],
)
def test_invalid_scope_contract_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ExternalServiceError) as exc_info:
        normalize_scope_result(payload)

    assert exc_info.value.code == "MCP_RESPONSE_INVALID"
