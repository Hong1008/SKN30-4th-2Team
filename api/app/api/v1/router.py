"""도메인별 v1 라우터를 모으는 진입점."""

from fastapi import APIRouter


router = APIRouter(prefix="/api/v1")
