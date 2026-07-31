"""검토 세션 생성과 사용자 선택 상태 변경 Use Case."""

import asyncio
import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

from sqlalchemy.orm import Session

from app.core.common.errors import (
    AppValidationError,
    ConflictError,
    ExternalServiceError,
    ExternalServiceTimeoutError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.config import Settings
from app.core.llm.mcp.types import WorkShieldMCPRuntime
from app.domains.review_sessions.domain import (
    ReviewSession,
    ReviewSessionState,
    ScopeStatus,
    SelectionSource,
)
from app.domains.review_sessions.file_validation import validate_document_content
from app.domains.review_sessions.policy import (
    DEFAULT_REVIEW_SESSION_POLICY,
    ReviewSessionPolicy,
)
from app.domains.review_sessions.repository import SqlAlchemyReviewSessionRepository
from app.domains.review_sessions.scope_normalization import normalize_scope_result
from app.core.security.session_tokens import issue_access_token
from app.core.storage.protocol import FileStorage


MVP_CONTRACT_TYPES = {
    "SW_FREELANCE",
    "SI_SUBCONTRACT",
    "SM_SUBCONTRACT",
}


def _validate_upload(
    file_name: str | None,
    content: bytes,
    policy: ReviewSessionPolicy = DEFAULT_REVIEW_SESSION_POLICY,
) -> str:
    """업로드 전 확장자·크기·실제 형식을 검증한다."""
    if not file_name or "." not in file_name:
        raise AppValidationError(
            code="FILE_EXTENSION_MISSING",
            message="파일 확장자를 확인해 주세요.",
            next_action="REUPLOAD",
        )
    extension = file_name.rsplit(".", 1)[1].lower()
    if extension not in policy.supported_file_extensions:
        raise UnsupportedMediaTypeError(
            code="UNSUPPORTED_FILE_TYPE",
            message="지원하지 않는 파일 형식입니다.",
            next_action="REUPLOAD",
        )
    if len(content) > policy.max_upload_size_bytes:
        raise PayloadTooLargeError(
            code="FILE_TOO_LARGE",
            message="파일 크기가 제한을 초과했습니다.",
            next_action="REUPLOAD",
        )
    if not content:
        raise AppValidationError(
            code="CORRUPTED_FILE",
            message="파일 내용을 읽을 수 없습니다.",
            next_action="REUPLOAD",
        )

    validate_document_content(extension, content)
    return extension


def _tool_payload(result: object) -> dict[str, Any]:
    """MCP 도구 결과에서 구조화 JSON만 추출한다."""
    if isinstance(result, dict):
        return result
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    content = result if isinstance(result, list) else getattr(result, "content", None)
    if isinstance(content, list):
        for item in content:
            text = (
                item.get("text")
                if isinstance(item, dict)
                else getattr(item, "text", None)
            )
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
    raise ExternalServiceError(
        code="MCP_RESPONSE_INVALID",
        message="검토 서비스 응답 형식이 올바르지 않습니다.",
        next_action="CONTACT_SUPPORT",
    )


async def _assess_scope(
    runtime: WorkShieldMCPRuntime,
    storage: FileStorage,
    storage_key: str,
    file_name: str,
    content: bytes,
    timeout: float,
) -> dict[str, Any]:
    """MCP assess_contract_scope를 현재 transport 계약에 맞게 호출한다."""
    tool = next(
        (
            candidate
            for candidate in runtime.tools
            if candidate.name == "assess_contract_scope"
        ),
        None,
    )
    if tool is None:
        raise ExternalServiceError(
            code="MCP_RESPONSE_INVALID",
            message="검토 서비스가 범위 판별 기능을 제공하지 않습니다.",
            next_action="CONTACT_SUPPORT",
        )
    try:
        if runtime.supports_file_path:
            with storage.local_path(storage_key) as local_path:
                result = await asyncio.wait_for(
                    tool.ainvoke({"file_path": str(local_path)}),
                    timeout=timeout,
                )
        else:
            result = await asyncio.wait_for(
                tool.ainvoke(
                    {
                        "file_content": base64.b64encode(content).decode("ascii"),
                        "file_name": file_name,
                    }
                ),
                timeout=timeout,
            )
    except (asyncio.TimeoutError, TimeoutError) as error:
        raise ExternalServiceTimeoutError(
            code="MCP_TIMEOUT",
            message="계약 범위 분석 시간이 초과되었습니다.",
            retryable=True,
            next_action="RETRY",
        ) from error
    except Exception as error:
        # 변동성 있는 외부 MCP 호출 오류를 내부 유형으로 래핑해
        # API 레이어가 일관된 응답을 반환하도록 한다.
        raise ExternalServiceError(
            code="MCP_TOOL_ERROR",
            message="검토 서비스와의 통신 중 오류가 발생했습니다.",
            retryable=True,
            next_action="RETRY",
        ) from error

    return _tool_payload(result)


async def create_review_session(
    *,
    db_session: Session,
    storage: FileStorage,
    runtime: WorkShieldMCPRuntime,
    settings: Settings,
    policy: ReviewSessionPolicy = DEFAULT_REVIEW_SESSION_POLICY,
    file_name: str | None,
    content: bytes,
) -> tuple[ReviewSession, str]:
    """파일을 저장하고 범위 판별 결과와 익명 접근 자격을 만든다."""
    extension = _validate_upload(file_name, content, policy)
    assert file_name is not None
    storage_key = storage.save(BytesIO(content), extension=extension)
    try:
        scope_result = normalize_scope_result(
            await _assess_scope(
                runtime,
                storage,
                storage_key,
                file_name,
                content,
                settings.workshield_mcp_timeout,
            )
        )
        scope_status = ScopeStatus(scope_result["status"])
        state = {
            ScopeStatus.EMPTY_DOCUMENT: ReviewSessionState.REUPLOAD_REQUIRED,
            ScopeStatus.OUT_OF_SCOPE: ReviewSessionState.OUT_OF_SCOPE_CONFIRMATION_REQUIRED,
        }.get(scope_status, ReviewSessionState.TYPE_SELECTION_REQUIRED)
        access = issue_access_token()
        now = datetime.now(UTC)
        entity = ReviewSession(
            id=f"ses_{uuid.uuid4().hex}",
            access_token_hash=access.digest,
            state=state,
            original_file_name=file_name,
            file_size_bytes=len(content),
            storage_key=storage_key,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(seconds=policy.session_ttl_seconds),
            scope_status=scope_status,
            scope_result=scope_result,
            suggested_contract_type=scope_result.get("suggested_contract_type"),
        )
        with db_session.begin():
            SqlAlchemyReviewSessionRepository(db_session).add(entity)
        return entity, access.raw
    except Exception:
        storage.delete(storage_key)
        raise


def select_contract_type(
    db_session: Session,
    entity: ReviewSession,
    *,
    selected_contract_type: str,
    selection_source: str,
) -> ReviewSession:
    """계약 유형을 저장하고 검토 가능 상태로 전환한다."""
    try:
        source = SelectionSource(selection_source)
    except ValueError as error:
        raise AppValidationError(
            code="REQUIRED_VALUE_MISSING",
            message="계약 유형 선택 경로가 올바르지 않습니다.",
            next_action="SELECT_CONTRACT_TYPE",
        ) from error
    if selected_contract_type not in MVP_CONTRACT_TYPES:
        raise AppValidationError(
            code="UNSUPPORTED_CONTRACT_TYPE",
            message="현재 지원하지 않는 계약 유형입니다.",
            next_action="SELECT_CONTRACT_TYPE",
        )
    if entity.scope_status is ScopeStatus.EMPTY_DOCUMENT:
        raise ConflictError(
            code="CONTRACT_TYPE_SELECTION_REQUIRED",
            message="현재 세션에서는 계약 유형을 선택할 수 없습니다.",
            next_action="REUPLOAD",
        )
    entity.selected_contract_type = selected_contract_type
    entity.selection_source = source
    entity.updated_at = datetime.now(UTC)
    if (
        entity.scope_status is ScopeStatus.OUT_OF_SCOPE
        and entity.out_of_scope_confirmed_at is None
    ):
        entity.state = ReviewSessionState.OUT_OF_SCOPE_CONFIRMATION_REQUIRED
    else:
        entity.state = ReviewSessionState.READY_TO_REVIEW
    SqlAlchemyReviewSessionRepository(db_session).save(entity)
    db_session.commit()
    return entity


def confirm_out_of_scope(
    db_session: Session,
    entity: ReviewSession,
    *,
    confirmed: bool,
) -> ReviewSession:
    """범위 외 문서의 계속 진행 확인을 저장한다."""
    if entity.scope_status is not ScopeStatus.OUT_OF_SCOPE or not confirmed:
        raise ConflictError(
            code="OUT_OF_SCOPE_CONFIRMATION_REQUIRED",
            message="범위 외 계속 진행 확인이 필요합니다.",
            next_action="CONFIRM_OUT_OF_SCOPE",
        )
    entity.out_of_scope_confirmed_at = datetime.now(UTC)
    entity.updated_at = datetime.now(UTC)
    entity.state = (
        ReviewSessionState.READY_TO_REVIEW
        if entity.selected_contract_type
        else ReviewSessionState.TYPE_SELECTION_REQUIRED
    )
    SqlAlchemyReviewSessionRepository(db_session).save(entity)
    db_session.commit()
    return entity


def delete_review_session(
    db_session: Session,
    storage: FileStorage,
    entity: ReviewSession,
) -> bool:
    """검토 시작 전 세션 레코드와 저장된 원본 파일을 폐기한다."""
    repository = SqlAlchemyReviewSessionRepository(db_session)
    if repository.has_reviews(entity.id):
        raise ConflictError(
            code="REVIEW_ALREADY_STARTED",
            message="검토가 시작된 세션은 파일 화면에서 제거할 수 없습니다.",
            next_action="START_NEW_REVIEW",
        )
    storage_key = entity.storage_key
    if storage_key is not None:
        storage.delete(storage_key)
    deleted = repository.delete(entity.id)
    db_session.commit()
    return deleted
