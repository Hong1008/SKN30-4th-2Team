"""검토 세션 생성·복구·선택 API."""

from fastapi import APIRouter, File, Request, Response, UploadFile

from app.config import SettingsDep
from app.core.access_control.dependencies import OwnedReviewSessionDep
from app.core.common.responses import (
    ApiResponse,
    COMMON_ERROR_RESPONSES,
    success_response,
)
from app.core.db.dependencies import DbSessionDep
from app.core.llm.mcp.dependencies import WorkShieldMCPRuntimeDep
from app.core.security.cookies import set_session_access_cookie
from app.core.storage.dependencies import FileStorageDep
from app.domains.review_sessions.schemas import (
    ContractTypeCandidate,
    ContractTypeSelectionRequest,
    OutOfScopeConfirmationRequest,
    ReviewSessionResponse,
    UploadInfo,
)
from app.domains.review_sessions.service import (
    confirm_out_of_scope,
    create_review_session,
    select_contract_type,
)

router = APIRouter(
    prefix="/review-sessions",
    tags=["review-sessions"],
    responses=COMMON_ERROR_RESPONSES,
)


def _response(entity) -> ReviewSessionResponse:
    """Domain 세션을 API DTO로 변환한다."""
    can_start = entity.state.value == "READY_TO_REVIEW"
    scope_result = entity.scope_result or {}
    candidates = scope_result.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
    allowed_actions = {
        "TYPE_SELECTION_REQUIRED": ["SELECT_CONTRACT_TYPE"],
        "OUT_OF_SCOPE_CONFIRMATION_REQUIRED": [
            "SELECT_CONTRACT_TYPE",
            "CONFIRM_OUT_OF_SCOPE",
        ],
        "READY_TO_REVIEW": ["START_REVIEW"],
        "REUPLOAD_REQUIRED": ["REUPLOAD"],
    }.get(entity.state.value, [])
    return ReviewSessionResponse(
        session_id=entity.id,
        review_state=entity.state,
        upload=UploadInfo(
            file_name=entity.original_file_name,
            size_bytes=entity.file_size_bytes,
            extension=entity.original_file_name.rsplit(".", 1)[-1].lower()
            if "." in entity.original_file_name
            else "",
        ),
        scope_status=entity.scope_status,
        scope_message=scope_result.get("message"),
        suggested_contract_type=entity.suggested_contract_type,
        candidates=[
            ContractTypeCandidate(
                contract_type=item["contract_type"],
                evidence_score=item["score"],
            )
            for item in candidates
            if isinstance(item, dict)
            and isinstance(item.get("contract_type"), str)
            and isinstance(item.get("score"), int)
        ],
        matched_clause_count=scope_result.get("matched_clause_count", 0),
        exclusion_markers=scope_result.get("exclusion_markers", []),
        selected_contract_type=entity.selected_contract_type,
        selection_source=entity.selection_source,
        out_of_scope_confirmed_at=entity.out_of_scope_confirmed_at,
        can_start_review=can_start,
        allowed_actions=allowed_actions,
        expires_at=entity.expires_at,
    )


@router.post(
    "",
    status_code=201,
    response_model=ApiResponse[ReviewSessionResponse],
)
async def create_session(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    db_session: DbSessionDep = None,
    storage: FileStorageDep = None,
    runtime: WorkShieldMCPRuntimeDep = None,
    settings: SettingsDep = None,
):
    """계약서 파일을 저장하고 익명 검토 세션을 생성한다."""
    content = await file.read(settings.max_upload_size_bytes + 1)
    entity, access_token = await create_review_session(
        db_session=db_session,
        storage=storage,
        runtime=runtime,
        settings=settings,
        file_name=file.filename,
        content=content,
    )
    set_session_access_cookie(response, token=access_token, settings=settings)
    return success_response(request, _response(entity))


@router.get(
    "/{session_id}",
    response_model=ApiResponse[ReviewSessionResponse],
)
def get_session(request: Request, owned: OwnedReviewSessionDep):
    """Cookie 소유자에게만 세션 상태를 반환한다."""
    return success_response(request, _response(owned))


@router.patch(
    "/{session_id}/contract-type",
    response_model=ApiResponse[ReviewSessionResponse],
)
def choose_contract_type(
    request: Request,
    owned: OwnedReviewSessionDep,
    payload: ContractTypeSelectionRequest,
    db_session: DbSessionDep,
):
    """소유 세션의 계약 유형을 확정한다."""
    entity = select_contract_type(
        db_session,
        owned,
        selected_contract_type=payload.selected_contract_type,
        selection_source=payload.selection_source,
    )
    return success_response(request, _response(entity))


@router.post(
    "/{session_id}/out-of-scope-confirmation",
    response_model=ApiResponse[ReviewSessionResponse],
)
def confirm_scope(
    request: Request,
    owned: OwnedReviewSessionDep,
    payload: OutOfScopeConfirmationRequest,
    db_session: DbSessionDep,
):
    """소유 세션의 범위 외 계속 진행을 확인한다."""
    entity = confirm_out_of_scope(db_session, owned, confirmed=payload.confirmed)
    return success_response(request, _response(entity))
