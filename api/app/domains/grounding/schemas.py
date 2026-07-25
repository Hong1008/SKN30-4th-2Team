"""Grounding API DTO."""

from enum import StrEnum

from pydantic import BaseModel, Field


class GroundingStatus(StrEnum):
    """법령 근거 조회 상태."""

    OK = "OK"
    NO_RESULT = "NO_RESULT"
    UNMAPPED_CATEGORY = "UNMAPPED_CATEGORY"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    TIMEOUT = "TIMEOUT"


class GroundingCategory(BaseModel):
    code: str = Field(description="카테고리 코드")
    label: str = Field(description="카테고리 표시명")


class GroundingItem(BaseModel):
    source_id: str = Field(description="법령 출처 식별자")
    law_name: str | None = Field(default=None, description="법령 명칭 (예: 민법)")
    article: str | None = Field(default=None, description="조항 번호 (예: 제390조)")
    text: str = Field(description="법령 조문 본문")
    source: str | None = Field(default=None, description="출처 기관 및 정보")
    source_url: str | None = Field(default=None, description="출처 URL 링크")


class GroundingResponse(BaseModel):
    grounding_status: GroundingStatus = Field(
        description="근거 조회 상태 (OK, NO_RESULT 등)"
    )
    category: GroundingCategory = Field(description="조회된 카테고리 정보")
    contract_type: str = Field(description="계약 유형 코드")
    items: list[GroundingItem] = Field(description="법령 근거 항목 목록")
    message: str | None = Field(default=None, description="상태 관련 메시지")
