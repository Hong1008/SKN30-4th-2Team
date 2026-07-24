"""배포 상태 확인을 위한 시스템 API."""

from fastapi import APIRouter

from app.config import SettingsDep


router = APIRouter(prefix="/health", tags=["system"])


@router.get("/live")
async def liveness() -> dict[str, str]:
    """프로세스가 HTTP 요청을 처리할 수 있음을 반환한다."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness(settings: SettingsDep) -> dict[str, str]:
    """비밀값 없이 현재 애플리케이션 설정 준비 상태를 반환한다."""
    return {
        "status": "ok",
        "environment": settings.app_env,
        "llm_provider": settings.llm_provider,
    }
