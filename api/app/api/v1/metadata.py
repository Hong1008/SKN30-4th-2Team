"""프론트 초기화용 공통 Metadata API."""

from fastapi import APIRouter, Header, Request, Response, status

from app.common.responses import (
    ApiResponse,
    COMMON_ERROR_RESPONSES,
    success_response,
)
from app.config import SettingsDep
from app.llm.mcp.dependencies import WorkShieldMCPRuntimeDep
from app.metadata.schemas import MetadataResponse
from app.metadata.service import get_metadata


router = APIRouter(tags=["metadata"], responses=COMMON_ERROR_RESPONSES)


@router.get("/metadata", response_model=ApiResponse[MetadataResponse])
async def metadata(
    request: Request,
    response: Response,
    runtime: WorkShieldMCPRuntimeDep,
    settings: SettingsDep,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    """MCP 코드 목록과 제품 정책을 캐시 가능한 단일 응답으로 제공한다."""
    payload, etag, stale = await get_metadata(request, runtime, settings)
    cache_control = (
        f"public, max-age={settings.metadata_cache_ttl_seconds}, "
        "stale-while-revalidate=600"
    )
    response.headers["Cache-Control"] = cache_control
    response.headers["ETag"] = etag
    if stale:
        response.headers["Warning"] = '110 - "Response is stale"'
    if if_none_match == etag:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={"Cache-Control": cache_control, "ETag": etag},
        )
    return success_response(request, payload)
