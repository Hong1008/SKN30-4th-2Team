"""배포 상태 확인을 위한 시스템 API."""

from fastapi import APIRouter, Request

from app.core.common.errors import ExternalServiceError
from app.core.db.dependencies import DatabaseDep
from app.core.llm.dependencies import MCPRuntimeDep


router = APIRouter(prefix="/health", tags=["system"])


@router.get("/live")
async def liveness() -> dict[str, str]:
    """프로세스가 HTTP 요청을 처리할 수 있음을 반환한다."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness(
    request: Request,
    database: DatabaseDep,
    _mcp_runtime: MCPRuntimeDep,
) -> dict[str, str]:
    """SQLite 연결과 MCP 런타임 초기화 여부를 확인한다."""
    if not database.is_ready():
        raise ExternalServiceError(
            code="DATABASE_UNAVAILABLE",
            message="데이터베이스가 준비되지 않았습니다.",
            retryable=True,
        )
    scheduler = getattr(request.app.state, "review_scheduler", None)
    if scheduler is not None and not scheduler.is_alive:
        raise ExternalServiceError(
            code="REVIEW_SCHEDULER_UNAVAILABLE",
            message="검토 작업 처리기가 준비되지 않았습니다.",
            retryable=True,
        )

    return {
        "status": "ok",
        "database": "ok",
        "mcp": "ok",
    }
