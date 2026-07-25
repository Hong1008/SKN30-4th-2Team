"""FastAPI에서 lifespan의 공유 WorkShield MCP runtime을 주입한다."""

from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.common.errors import ExternalServiceError
from app.core.llm.mcp.types import WorkShieldMCPRuntime


async def get_workshield_runtime(request: Request) -> WorkShieldMCPRuntime:
    runtime = getattr(request.app.state, "workshield_mcp", None)
    if runtime is None:
        raise ExternalServiceError(
            code="MCP_UNAVAILABLE",
            message="검토 서비스를 사용할 수 없습니다.",
            retryable=True,
            next_action="RETRY",
        )
    return cast(WorkShieldMCPRuntime, runtime)


WorkShieldMCPRuntimeDep = Annotated[
    WorkShieldMCPRuntime,
    Depends(get_workshield_runtime),
]
