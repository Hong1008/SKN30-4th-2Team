"""저장된 검토 스냅샷의 프론트 결과 DTO 변환을 검증한다."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.domains.reviews.domain import MCPReviewStatus, Review, ReviewState
from app.domains.reviews.presentation import (
    present_review_results,
    standard_contract_label,
)


def test_standard_contract_label_uses_safe_user_facing_names() -> None:
    assert (
        standard_contract_label("SW_FREELANCE")
        == "SW 프리랜서 용역 표준계약서"
    )
    assert (
        standard_contract_label("SI_SUBCONTRACT")
        == "SI 하도급 표준계약서"
    )
    assert (
        standard_contract_label("SM_SUBCONTRACT")
        == "SM 하도급 표준계약서"
    )
    assert standard_contract_label("UNKNOWN_INTERNAL_TYPE") == "표준계약서"


def test_result_presentation_uses_metadata_labels_and_separates_missing() -> None:
    now = datetime.now(UTC)
    review = Review.restore(
        review_id="rev_result",
        session_id="ses_result",
        idempotency_key="operation",
        state=ReviewState.COMPLETED,
        contract_type="SW_FREELANCE",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        mcp_review_status=MCPReviewStatus.OK,
        result={
            "status": "OK",
            "contract_type": "SW_FREELANCE",
            "clause_results": [
                {
                    "user_clause_id": "uc_rev_result_1",
                    "user_clause": "손해배상 조항",
                    "deviation": "EXTRA",
                    "match": {
                        "status": "CANDIDATE_SELECTED",
                        "standard": {
                            "clause_id": "std_1",
                            "contract_type": "SW_FREELANCE",
                            "category": "LIABILITY",
                            "title": "손해배상",
                            "text": "표준 조항",
                            "source": "표준계약서",
                            "version": "2026",
                        },
                        "score": 0.9,
                    },
                    "toxic_patterns": ["UNFAIR_DAMAGE_CLAIM"],
                }
            ],
            "missing_standard_clauses": [
                {
                    "standard": {
                        "clause_id": "std_2",
                        "contract_type": "SW_FREELANCE",
                        "category": "PAYMENT",
                        "title": "대금 지급",
                        "text": "표준 조항",
                        "source": "표준계약서",
                        "version": "2026",
                    }
                }
            ],
            "message": None,
        },
        started_at=now,
        completed_at=now,
    )
    metadata_cache = {
        "payload": SimpleNamespace(
            categories=[
                SimpleNamespace(code="LIABILITY", label="책임·손해배상"),
                SimpleNamespace(code="PAYMENT", label="대금 지급"),
            ],
            toxic_patterns=[
                SimpleNamespace(
                    code="UNFAIR_DAMAGE_CLAIM",
                    label="과도한 손해배상 표현",
                )
            ],
        )
    }

    result = present_review_results(review, metadata_cache=metadata_cache)

    assert result.summary.model_dump() == {
        "clause_results": {
            "total": 1,
            "NONE": 0,
            "EXTRA": 1,
            "NO_MATCH": 0,
        },
        "missing_standard_clauses": 1,
        "toxic_pattern_candidates": 1,
    }
    assert result.clause_results[0].match.standard is not None
    matched_standard = result.clause_results[0].match.standard
    assert matched_standard.category.label == "책임·손해배상"
    assert (
        matched_standard.standard_contract_label
        == "SW 프리랜서 용역 표준계약서"
    )
    assert set(matched_standard.model_dump()) == {
        "standard_contract_label",
        "category",
        "title",
        "text",
    }
    assert result.clause_results[0].toxic_patterns[0].label == "과도한 손해배상 표현"
    missing_standard = result.missing_standard_clauses[0].standard
    assert missing_standard.category.label == "대금 지급"
    assert (
        missing_standard.standard_contract_label
        == "SW 프리랜서 용역 표준계약서"
    )
    assert set(missing_standard.model_dump()) == {
        "standard_contract_label",
        "category",
        "title",
        "text",
    }
    stored_standard = review.result["clause_results"][0]["match"]["standard"]
    assert stored_standard["clause_id"] == "std_1"
    assert stored_standard["source"] == "표준계약서"
    assert stored_standard["version"] == "2026"
