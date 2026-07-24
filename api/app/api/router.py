"""시스템 API와 버전 API를 애플리케이션에 연결한다."""

from fastapi import APIRouter

from app.api.system import router as system_router
from app.api.v1.router import router as v1_router


router = APIRouter()
router.include_router(system_router)
router.include_router(v1_router)
