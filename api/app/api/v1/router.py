"""도메인별 v1 라우터를 모으는 진입점."""

from fastapi import APIRouter

from app.api.v1.metadata import router as metadata_router
from app.api.v1.review_sessions import router as review_sessions_router
from app.api.v1.reviews import router as reviews_router


router = APIRouter(prefix="/api/v1")
router.include_router(metadata_router)
router.include_router(review_sessions_router)
router.include_router(reviews_router)
