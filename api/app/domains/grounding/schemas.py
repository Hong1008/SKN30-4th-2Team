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


class GroundingStatusGuidance(BaseModel):
    """법령 조회 상태별 사용자 안내와 후속 행동."""

    code: GroundingStatus
    label: str
    message: str
    retryable: bool
    next_action: str | None = None


GROUNDING_STATUS_GUIDANCE: dict[GroundingStatus, GroundingStatusGuidance] = {
    GroundingStatus.OK: GroundingStatusGuidance(
        code=GroundingStatus.OK,
        label="조회 완료",
        message="관련 법령 참고자료를 확인했습니다.",
        retryable=False,
    ),
    GroundingStatus.NO_RESULT: GroundingStatusGuidance(
        code=GroundingStatus.NO_RESULT,
        label="조회 결과 없음",
        message="현재 조회 조건에서 관련 법령 원문이 조회되지 않았습니다. 법령 부재를 의미하지 않으므로 별도 확인이 필요합니다.",
        retryable=False,
    ),
    GroundingStatus.UNMAPPED_CATEGORY: GroundingStatusGuidance(
        code=GroundingStatus.UNMAPPED_CATEGORY,
        label="연결 정보 없음",
        message="현재 정책에 이 카테고리와 연결된 특정 법령 조문이 없습니다. 별도 확인이 필요합니다.",
        retryable=False,
    ),
    GroundingStatus.TIMEOUT: GroundingStatusGuidance(
        code=GroundingStatus.TIMEOUT,
        label="조회 시간 초과",
        message="법령 원문 조회 시간이 초과되었습니다. 잠시 후 다시 조회해 주세요.",
        retryable=True,
        next_action="RELOAD_GROUNDING",
    ),
    GroundingStatus.UPSTREAM_ERROR: GroundingStatusGuidance(
        code=GroundingStatus.UPSTREAM_ERROR,
        label="법령 서비스 오류",
        message="외부 법령 서비스 오류로 원문을 확인하지 못했습니다. 잠시 후 다시 조회해 주세요.",
        retryable=True,
        next_action="RELOAD_GROUNDING",
    ),
}


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
    retryable: bool = Field(
        default=False, description="동일 조회를 재시도할 수 있는지 여부"
    )
    next_action: str | None = Field(default=None, description="권장 후속 행동 코드")
