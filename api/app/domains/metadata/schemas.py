"""Metadata API DTO."""

from datetime import datetime
from pydantic import BaseModel, Field

from app.domains.chat.schemas import ChatOutcome
from app.domains.grounding.schemas import GroundingStatus, GroundingStatusGuidance
from app.domains.review_sessions.domain import ScopeStatus, SelectionSource
from app.domains.suggestions.schemas import SuggestionOutcome


class MetadataCode(BaseModel):
    code: str = Field(description="식별 코드")
    label: str = Field(description="화면 표시명")
    description: str | None = Field(default=None, description="코드 상세 설명")
    enabled_for_mvp: bool | None = Field(
        default=None, description="MVP 선택 활성화 여부"
    )


class CategoryMetadata(BaseModel):
    code: str = Field(description="카테고리 코드")
    label: str = Field(description="카테고리 표시명")
    description: str | None = Field(default=None, description="카테고리 설명")
    anchors: list[str] = Field(
        default_factory=list, description="카테고리 앵커 키워드 목록"
    )


class ToxicPatternMetadata(BaseModel):
    code: str = Field(description="독소/주의 패턴 코드")
    label: str = Field(description="독소/주의 패턴 표시명")
    category: str | None = Field(default=None, description="연관 카테고리 코드")
    example_count: int = Field(default=0, description="예시 문구 개수")


class ResultCodeMetadata(BaseModel):
    code: str = Field(description="결과 코드")
    label: str = Field(description="결과 코드 표시명")


class ProgressStageMetadata(BaseModel):
    code: str = Field(description="검토 진행 단계 코드")
    label: str = Field(description="검토 진행 단계 화면 표시명")


class FilePolicy(BaseModel):
    extensions: list[str] = Field(description="허용 파일 확장자 목록")
    max_size_bytes: int = Field(description="최대 업로드 허용 파일 크기 (바이트)")
    single_file_only: bool = Field(
        default=True, description="단일 파일 업로드 전용 여부"
    )
    encrypted_file_allowed: bool = Field(
        default=False, description="암호화 파일 허용 여부"
    )


class FeatureFlags(BaseModel):
    chat: bool = Field(default=True, description="질의응답(챗봇) 기능 활성화 여부")
    basic_suggestion: bool = Field(
        default=True, description="기본 협의 문구 제안 기능 활성화 여부"
    )
    confidence_score: bool = Field(default=False, description="신뢰도 점수 노출 여부")
    suggestion_edit: bool = Field(
        default=False, description="제안 문구 편집/임시저장 기능 활성화 여부"
    )
    single_clause_rereview: bool = Field(
        default=False, description="단일 조항 재검토 기능 활성화 여부"
    )
    server_side_cancel: bool = Field(
        default=True, description="서버 사이드 검토 취소/폐기 기능 활성화 여부"
    )


class MetadataResponse(BaseModel):
    schema_version: str = Field(default="1.2", description="메타데이터 스키마 버전")
    updated_at: datetime = Field(description="메타데이터 최종 업데이트 일시")
    contract_types: list[MetadataCode] = Field(description="지원 계약 유형 목록")
    categories: list[CategoryMetadata] = Field(description="검토 카테고리 목록")
    toxic_patterns: list[ToxicPatternMetadata] = Field(
        description="주의/독소 패턴 목록"
    )
    scope_statuses: list[ScopeStatus] = Field(description="범위 판별 상태 코드 목록")
    review_states: list[str] = Field(description="검토 세션/진행 상태 코드 목록")
    result_codes: list[str] = Field(description="검토 결과 코드 목록")
    result_code_details: list[ResultCodeMetadata] = Field(
        description="검토 결과 코드 상세 목록"
    )
    progress_stages: list[str] = Field(description="검토 진행 단계 코드 목록")
    progress_stage_details: list[ProgressStageMetadata] = Field(
        description="검토 진행 단계 코드 및 화면 표시명 목록"
    )
    grounding_statuses: list[GroundingStatus] = Field(
        description="법령 근거 조회 상태 코드 목록"
    )
    grounding_status_details: list[GroundingStatusGuidance] = Field(
        description="법령 근거 조회 상태별 사용자 안내"
    )
    chat_outcomes: list[ChatOutcome] = Field(description="질의응답 결과 유형 목록")
    draft_outcomes: list[SuggestionOutcome] = Field(
        description="제안 생성 결과 유형 목록"
    )
    error_codes: list[str] = Field(description="시스템 에러 코드 목록")
    selection_sources: list[SelectionSource] = Field(
        description="계약 유형 선택 경로 목록"
    )
    next_actions: list[str] = Field(description="권장 다음 행동 코드 목록")
    file_policy: FilePolicy = Field(description="업로드 파일 제한 정책")
    features: FeatureFlags = Field(description="기능 플래그 목록")
