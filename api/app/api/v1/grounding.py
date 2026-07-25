"""검토 결과 법령 참고자료(Grounding) 조회 API."""

from fastapi import APIRouter, Request

from app.config import SettingsDep
from app.core.access_control.dependencies import OwnedReviewDep
from app.core.common.responses import (
    ApiResponse,
    COMMON_ERROR_RESPONSES,
    success_response,
)
from app.core.llm.mcp.dependencies import WorkShieldMCPRuntimeDep
from app.domains.grounding.schemas import GroundingResponse
from app.domains.grounding.service import get_review_grounding

router = APIRouter(
    prefix="/reviews",
    tags=["reviews"],
    responses=COMMON_ERROR_RESPONSES,
)


@router.get(
    "/{review_id}/grounding",
    response_model=ApiResponse[GroundingResponse],
)
async def get_grounding(
    request: Request,
    owned: OwnedReviewDep,
    runtime: WorkShieldMCPRuntimeDep,
    settings: SettingsDep,
    category: str,
):
    """현재 검토 결과의 category에 해당하는 법령 참고자료를 조회한다."""
    data = await get_review_grounding(owned, category, runtime, settings)
    return success_response(request, data)
