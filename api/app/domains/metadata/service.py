"""MCP 메타데이터 조회, 정규화, 메모리 캐시."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request

from app.core.common.errors import ExternalServiceError
from app.core.llm.mcp.types import WorkShieldMCPRuntime
from app.domains.metadata.policy import DEFAULT_METADATA_POLICY, MetadataPolicy
from app.domains.metadata.schemas import (
    CategoryMetadata,
    FeatureFlags,
    FilePolicy,
    MetadataCode,
    MetadataResponse,
    ProgressStageMetadata,
    ResultCodeMetadata,
    ToxicPatternMetadata,
)
from app.domains.grounding.schemas import GROUNDING_STATUS_GUIDANCE
from app.domains.review_sessions.domain import (
    ReviewSessionState,
    ScopeStatus,
    SelectionSource,
)
from app.domains.review_sessions.policy import (
    DEFAULT_REVIEW_SESSION_POLICY,
    ReviewSessionPolicy,
)
from app.domains.review_sessions.service import MVP_CONTRACT_TYPES, _tool_payload
from app.domains.reviews.domain import ReviewState


FALLBACK_CONTRACT_TYPES = {
    "SW_FREELANCE": "SW 프리랜서 용역",
    "SI_SUBCONTRACT": "SI 하도급",
    "SM_SUBCONTRACT": "SM 하도급",
    "SW_EMPLOYMENT": "SW 근로계약",
}
PROGRESS_STAGE_LABELS = {
    "PREPARE": "검토 준비",
    "BATCH_SEARCH": "조항 검색 및 분류",
    "RERANK": "관련 조항 재정렬",
    "CLAUSE_REVIEW": "조항 비교 검토",
    "MISSING_DETECTION": "누락 조항 확인",
    "RESULT_ASSEMBLY": "결과 정리",
}
PROGRESS_STAGES = list(PROGRESS_STAGE_LABELS)
ERROR_CODES = [
    "VALIDATION_ERROR",
    "RESOURCE_NOT_FOUND",
    "SESSION_EXPIRED",
    "IDEMPOTENCY_KEY_REUSED",
    "REVIEW_ALREADY_RUNNING",
    "REVIEW_NOT_COMPLETED",
    "MCP_TIMEOUT",
    "CORPUS_UNAVAILABLE",
    "INVALID_CONFIG",
    "PIPELINE_ERROR",
    "LLM_TIMEOUT",
    "LLM_OUTPUT_INVALID",
    "GENERATED_FACT_NOT_GROUNDED",
]
RESULT_CODE_LABELS = {
    "NONE": "표준 대응 후보 있음",
    "EXTRA": "별도 확인 필요",
    "NO_MATCH": "표준조항 검색 후보 없음",
    "MISSING": "표준조항 누락 가능성",
}


def _items(payload: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    data = payload.get("data")
    return data if isinstance(data, list) else []


def _code_items(values: list[Any]) -> list[MetadataCode]:
    normalized: list[MetadataCode] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, str):
            code, label, description = value, value, None
        elif isinstance(value, dict):
            raw_code = value.get("code") or value.get("id") or value.get("value")
            if not isinstance(raw_code, str) or not raw_code.strip():
                continue
            code = raw_code.strip()
            label = str(value.get("label") or value.get("name") or code)
            raw_description = value.get("description")
            description = str(raw_description) if raw_description is not None else None
        else:
            continue
        if code in seen:
            continue
        seen.add(code)
        normalized.append(
            MetadataCode(
                code=code,
                label=label,
                description=description,
                enabled_for_mvp=code in MVP_CONTRACT_TYPES,
            )
        )
    return normalized


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _categories(values: list[Any]) -> list[CategoryMetadata]:
    normalized: list[CategoryMetadata] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, str):
            code = value.strip()
            if not code:
                continue
            label = code
            description = None
            anchors: list[str] = []
        elif isinstance(value, dict):
            code = _optional_text(
                value.get("code") or value.get("id") or value.get("value")
            )
            if code is None:
                continue
            description = _optional_text(value.get("description"))
            label = (
                _optional_text(value.get("label"))
                or _optional_text(value.get("name"))
                or description
                or code
            )
            raw_anchors = value.get("anchors")
            anchors = (
                [
                    anchor
                    for item in raw_anchors
                    if (anchor := _optional_text(item)) is not None
                ]
                if isinstance(raw_anchors, list)
                else []
            )
        else:
            continue
        if code in seen:
            continue
        seen.add(code)
        normalized.append(
            CategoryMetadata(
                code=code,
                label=label,
                description=description,
                anchors=anchors,
            )
        )
    return normalized


def _toxic_patterns(values: list[Any]) -> list[ToxicPatternMetadata]:
    normalized: list[ToxicPatternMetadata] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, str):
            code = value.strip()
            if not code:
                continue
            label = code
            category = None
            example_count = 0
        elif isinstance(value, dict):
            code = _optional_text(
                value.get("pattern")
                or value.get("code")
                or value.get("id")
                or value.get("value")
            )
            if code is None:
                continue
            label = (
                _optional_text(value.get("title"))
                or _optional_text(value.get("label"))
                or _optional_text(value.get("name"))
                or code
            )
            category = _optional_text(value.get("category"))
            raw_example_count = value.get("example_count", 0)
            if (
                not isinstance(raw_example_count, int)
                or isinstance(raw_example_count, bool)
                or raw_example_count < 0
            ):
                continue
            example_count = raw_example_count
        else:
            continue
        if code in seen:
            continue
        seen.add(code)
        normalized.append(
            ToxicPatternMetadata(
                code=code,
                label=label,
                category=category,
                example_count=example_count,
            )
        )
    return normalized


async def _invoke_optional(
    runtime: WorkShieldMCPRuntime,
    tool_name: str,
) -> dict[str, Any]:
    tool = next(
        (candidate for candidate in runtime.tools if candidate.name == tool_name),
        None,
    )
    if tool is None:
        return {}
    return _tool_payload(await tool.ainvoke({}))


def _etag(payload: MetadataResponse) -> str:
    content = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f'"metadata-{hashlib.sha256(content).hexdigest()[:16]}"'


async def get_metadata(
    request: Request,
    runtime: WorkShieldMCPRuntime,
    review_session_policy: ReviewSessionPolicy = DEFAULT_REVIEW_SESSION_POLICY,
    metadata_policy: MetadataPolicy = DEFAULT_METADATA_POLICY,
) -> tuple[MetadataResponse, str, bool]:
    """유효 캐시를 우선 사용하고 MCP 장애 시 마지막 캐시를 제공한다."""
    now = datetime.now(UTC)
    cached = getattr(request.app.state, "metadata_cache", None)
    if isinstance(cached, dict) and cached.get("expires_at", now) > now:
        return cached["payload"], cached["etag"], False

    try:
        contracts_payload, categories_payload, toxic_payload = await asyncio.gather(
            _invoke_optional(runtime, "list_contract_types"),
            _invoke_optional(runtime, "list_categories"),
            _invoke_optional(runtime, "list_toxic_pattern_details"),
        )
        contract_types = _code_items(
            _items(contracts_payload, "contract_types", "types", "items")
        )
        contract_types = [
            item.model_copy(
                update={"label": FALLBACK_CONTRACT_TYPES.get(item.code, item.label)}
            )
            for item in contract_types
        ]
        known_codes = {item.code for item in contract_types}
        for code, label in FALLBACK_CONTRACT_TYPES.items():
            if code not in known_codes:
                contract_types.append(
                    MetadataCode(
                        code=code,
                        label=label,
                        enabled_for_mvp=code in MVP_CONTRACT_TYPES,
                    )
                )
        categories = _categories(_items(categories_payload, "categories", "items"))
        toxic_patterns = _toxic_patterns(
            _items(toxic_payload, "toxic_patterns", "patterns", "items")
        )
        payload = MetadataResponse(
            updated_at=now,
            contract_types=contract_types,
            categories=categories,
            toxic_patterns=toxic_patterns,
            scope_statuses=[value.value for value in ScopeStatus],
            review_states=list(
                dict.fromkeys(
                    [value.value for value in ReviewSessionState]
                    + [value.value for value in ReviewState]
                )
            ),
            result_codes=list(RESULT_CODE_LABELS),
            result_code_details=[
                ResultCodeMetadata(code=code, label=label)
                for code, label in RESULT_CODE_LABELS.items()
            ],
            progress_stages=PROGRESS_STAGES,
            progress_stage_details=[
                ProgressStageMetadata(code=code, label=label)
                for code, label in PROGRESS_STAGE_LABELS.items()
            ],
            grounding_statuses=[
                "OK",
                "NO_RESULT",
                "UNMAPPED_CATEGORY",
                "UPSTREAM_ERROR",
                "TIMEOUT",
            ],
            grounding_status_details=list(GROUNDING_STATUS_GUIDANCE.values()),
            chat_outcomes=[
                "ANSWERED",
                "REFUSED",
                "INSUFFICIENT_GROUNDING",
                "LLM_OUTPUT_INVALID",
            ],
            draft_outcomes=[
                "GENERATED",
                "INSUFFICIENT_GROUNDING",
                "REQUIRED_VALUE_MISSING",
                "GENERATED_FACT_NOT_GROUNDED",
                "LLM_OUTPUT_INVALID",
            ],
            error_codes=ERROR_CODES,
            selection_sources=[value.value for value in SelectionSource],
            next_actions=[
                "REUPLOAD",
                "SELECT_CONTRACT_TYPE",
                "CONFIRM_OUT_OF_SCOPE",
                "RETRY_REVIEW",
                "RELOAD_GROUNDING",
                "START_NEW_REVIEW",
                "CONTACT_SUPPORT",
            ],
            file_policy=FilePolicy(
                extensions=list(review_session_policy.supported_file_extensions),
                max_size_bytes=review_session_policy.max_upload_size_bytes,
            ),
            features=FeatureFlags(),
        )
        etag = _etag(payload)
        request.app.state.metadata_cache = {
            "payload": payload,
            "etag": etag,
            "expires_at": now
            + timedelta(seconds=metadata_policy.cache_ttl_seconds),
        }
        return payload, etag, False
    except Exception as error:
        if isinstance(cached, dict) and "payload" in cached and "etag" in cached:
            return cached["payload"], cached["etag"], True
        raise ExternalServiceError(
            code="MCP_METADATA_UNAVAILABLE",
            message="메타데이터를 불러오지 못했습니다.",
            retryable=True,
            next_action="RETRY",
        ) from error
