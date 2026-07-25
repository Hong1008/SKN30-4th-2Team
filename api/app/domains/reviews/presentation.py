"""저장된 MCP 검토 스냅샷을 프론트 결과 DTO로 변환한다."""

from collections import Counter
from typing import Any

from app.domains.metadata.service import RESULT_CODE_LABELS
from app.domains.reviews.domain import Review
from app.domains.reviews.schemas import (
    CodeLabel,
    NormalizedReviewResult,
    ReviewClauseResultCounts,
    ReviewClauseResultResponse,
    ReviewResultMatch,
    ReviewResultMetadata,
    ReviewResultsResponse,
    ReviewResultsSummary,
    ReviewResultStandardClause,
    MissingStandardClauseResponse,
)


DISCLAIMER = "표준계약서 대비 검토 후보이며 법률 자문이 아닙니다."
CLAUSE_EXPLANATIONS = {
    "NONE": "표준조항 대응 후보가 확인된 조항입니다.",
    "EXTRA": (
        "표준조항 후보는 있으나 대응 기준에 미치지 못해 추가 확인이 필요한 조항입니다."
    ),
    "NO_MATCH": "대응할 표준조항 후보를 찾지 못해 추가 확인이 필요한 조항입니다.",
}
MISSING_EXPLANATION = (
    "이 표준조항에 대응하는 내용을 계약서 전체에서 찾지 못해 "
    "포함 여부 확인이 필요합니다."
)


def _metadata_labels(
    metadata_cache: object,
) -> tuple[dict[str, str], dict[str, str]]:
    if not isinstance(metadata_cache, dict):
        return {}, {}
    payload = metadata_cache.get("payload")
    categories = getattr(payload, "categories", [])
    toxic_patterns = getattr(payload, "toxic_patterns", [])
    return (
        {
            item.code: item.label
            for item in categories
            if getattr(item, "code", None) and getattr(item, "label", None)
        },
        {
            item.code: item.label
            for item in toxic_patterns
            if getattr(item, "code", None) and getattr(item, "label", None)
        },
    )


def _standard(
    raw: Any,
    category_labels: dict[str, str],
) -> ReviewResultStandardClause:
    return ReviewResultStandardClause(
        clause_id=raw.clause_id,
        contract_type=raw.contract_type,
        category=CodeLabel(
            code=raw.category,
            label=category_labels.get(raw.category, raw.category),
        ),
        title=raw.title,
        text=raw.text,
        source=raw.source,
        version=raw.version,
    )


def present_review_results(
    review: Review,
    *,
    metadata_cache: object = None,
) -> ReviewResultsResponse:
    """검증된 저장 스냅샷에서 문서화된 결과 응답을 계산한다."""
    normalized = NormalizedReviewResult.model_validate(review.result)
    category_labels, toxic_labels = _metadata_labels(metadata_cache)
    counts = Counter(item.deviation.value for item in normalized.clause_results)
    clause_results = [
        ReviewClauseResultResponse(
            user_clause_id=item.user_clause_id,
            user_clause=item.user_clause,
            deviation=CodeLabel(
                code=item.deviation.value,
                label=RESULT_CODE_LABELS[item.deviation.value],
            ),
            match=ReviewResultMatch(
                status=item.match.status,
                standard=(
                    _standard(item.match.standard, category_labels)
                    if item.match.status == "CANDIDATE_SELECTED"
                    else None
                ),
            ),
            explanation=CLAUSE_EXPLANATIONS[item.deviation.value],
            toxic_patterns=[
                CodeLabel(
                    code=code,
                    label=toxic_labels.get(code, code),
                )
                for code in item.toxic_patterns
            ],
        )
        for item in normalized.clause_results
    ]
    missing = [
        MissingStandardClauseResponse(
            result_type=CodeLabel(
                code="MISSING",
                label=RESULT_CODE_LABELS["MISSING"],
            ),
            standard=_standard(item.standard, category_labels),
            explanation=MISSING_EXPLANATION,
        )
        for item in normalized.missing_standard_clauses
    ]
    return ReviewResultsResponse(
        review=ReviewResultMetadata(
            review_id=review.id,
            review_state=review.state.value,
            mcp_review_status=normalized.status.value,
            contract_type=normalized.contract_type,
            started_at=review.started_at,
            completed_at=review.completed_at,
            expires_at=review.expires_at,
            disclaimer=DISCLAIMER,
        ),
        summary=ReviewResultsSummary(
            clause_results=ReviewClauseResultCounts(
                total=len(clause_results),
                NONE=counts["NONE"],
                EXTRA=counts["EXTRA"],
                NO_MATCH=counts["NO_MATCH"],
            ),
            missing_standard_clauses=len(missing),
            toxic_pattern_candidates=sum(
                len(item.toxic_patterns) for item in normalized.clause_results
            ),
        ),
        clause_results=clause_results,
        missing_standard_clauses=missing,
    )
