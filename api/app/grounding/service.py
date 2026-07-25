"""MCP grounding 조회와 공개 DTO 정규화."""

import asyncio
import re
from typing import Any
from urllib.parse import urlparse

from app.common.errors import AppValidationError, ConflictError
from app.config import Settings
from app.grounding.schemas import (
    GroundingCategory,
    GroundingItem,
    GroundingResponse,
)
from app.llm.mcp.types import WorkShieldMCPRuntime
from app.review_sessions.service import _tool_payload
from app.reviews.domain import Review, ReviewState


CATEGORY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
GROUNDING_STATUSES = {
    "OK",
    "NO_RESULT",
    "UNMAPPED_CATEGORY",
    "UPSTREAM_ERROR",
    "TIMEOUT",
}


def _safe_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _result_categories(result: dict[str, Any] | None) -> set[str]:
    categories: set[str] = set()
    if not result:
        return categories
    values = list(result.get("clause_results") or []) + list(
        result.get("missing_standard_clauses") or []
    )
    for item in values:
        if not isinstance(item, dict):
            continue
        direct = item.get("category")
        if isinstance(direct, str):
            categories.add(direct)
        match = item.get("match")
        standard = match.get("standard") if isinstance(match, dict) else None
        if not isinstance(standard, dict):
            standard = item.get("standard")
        if isinstance(standard, dict) and isinstance(standard.get("category"), str):
            categories.add(standard["category"])
    return categories


def validate_grounding_request(review: Review, category: str) -> str:
    if review.state is not ReviewState.COMPLETED or not review.result:
        raise ConflictError(
            code="REVIEW_NOT_COMPLETED",
            message="완료된 검토에서만 법령 근거를 조회할 수 있습니다.",
        )
    normalized = category.strip().upper()
    if not CATEGORY_PATTERN.fullmatch(normalized):
        raise AppValidationError(
            code="VALIDATION_ERROR",
            message="category 형식이 올바르지 않습니다.",
            field="category",
        )
    available = _result_categories(review.result)
    if available and normalized not in {value.upper() for value in available}:
        raise AppValidationError(
            code="CATEGORY_NOT_IN_REVIEW",
            message="현재 검토 결과에 포함되지 않은 category입니다.",
            field="category",
        )
    return normalized


def _normalize_items(payload: dict[str, Any]) -> list[GroundingItem]:
    raw_items = payload.get("grounding")
    if not isinstance(raw_items, list):
        raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return []
    items: list[GroundingItem] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            continue
        text = raw.get("text") or raw.get("content") or raw.get("body")
        if not isinstance(text, str) or not text.strip():
            continue
        source_id = raw.get("source_id") or raw.get("id") or f"law_{index + 1}"
        items.append(
            GroundingItem(
                source_id=str(source_id),
                law_name=str(raw["law_name"]) if raw.get("law_name") else None,
                article=str(raw["article"]) if raw.get("article") else None,
                text=text,
                source=str(raw["source"]) if raw.get("source") else None,
                source_url=_safe_url(raw.get("source_url") or raw.get("url")),
            )
        )
    return items


async def get_review_grounding(
    review: Review,
    category: str,
    runtime: WorkShieldMCPRuntime,
    settings: Settings,
) -> GroundingResponse:
    """현재 review의 contract_type과 검증된 category로만 MCP를 호출한다."""
    normalized_category = validate_grounding_request(review, category)
    tool = next(
        (
            candidate
            for candidate in runtime.tools
            if candidate.name == "get_category_grounding"
        ),
        None,
    )
    if tool is None:
        return GroundingResponse(
            grounding_status="UPSTREAM_ERROR",
            category=GroundingCategory(
                code=normalized_category,
                label=normalized_category,
            ),
            contract_type=review.contract_type,
            items=[],
            message="법령 근거 조회 기능을 사용할 수 없습니다.",
        )
    try:
        result = await asyncio.wait_for(
            tool.ainvoke(
                {
                    "contract_type": review.contract_type,
                    "category": normalized_category,
                }
            ),
            timeout=settings.workshield_mcp_timeout,
        )
        payload = _tool_payload(result)
        raw_status = str(payload.get("status", "UPSTREAM_ERROR")).upper()
        grounding_status = (
            raw_status if raw_status in GROUNDING_STATUSES else "UPSTREAM_ERROR"
        )
        items = _normalize_items(payload) if grounding_status == "OK" else []
        if grounding_status == "OK" and not items:
            grounding_status = "NO_RESULT"
        raw_category = payload.get("category")
        label = normalized_category
        if isinstance(raw_category, dict):
            label = str(raw_category.get("label") or normalized_category)
        elif isinstance(payload.get("category_label"), str):
            label = payload["category_label"]
        return GroundingResponse(
            grounding_status=grounding_status,
            category=GroundingCategory(code=normalized_category, label=label),
            contract_type=review.contract_type,
            items=items,
            message=(
                str(payload["message"])
                if payload.get("message") is not None
                else None
            ),
        )
    except (asyncio.TimeoutError, TimeoutError):
        return GroundingResponse(
            grounding_status="TIMEOUT",
            category=GroundingCategory(
                code=normalized_category,
                label=normalized_category,
            ),
            contract_type=review.contract_type,
            items=[],
            message="법령 근거 조회 시간이 초과되었습니다.",
        )
    except Exception:
        return GroundingResponse(
            grounding_status="UPSTREAM_ERROR",
            category=GroundingCategory(
                code=normalized_category,
                label=normalized_category,
            ),
            contract_type=review.contract_type,
            items=[],
            message="법령 근거를 조회하지 못했습니다.",
        )
