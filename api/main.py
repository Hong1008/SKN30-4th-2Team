"""WorkShield API 진입점."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import SettingsDep, get_settings
from app.llm.mcp import open_workshield_mcp


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """WorkShield MCP session을 API 애플리케이션 수명과 함께 관리한다."""
    async with open_workshield_mcp(get_settings()) as runtime:
        app.state.workshield_mcp = runtime
        try:
            yield
        finally:
            del app.state.workshield_mcp


app = FastAPI(title="WorkShield API", version="0.1.0", lifespan=lifespan)


@app.get("/health", tags=["system"])
async def health(settings: SettingsDep) -> dict[str, str]:
    """비밀값을 노출하지 않는 최소 상태 확인 엔드포인트."""
    return {
        "status": "ok",
        "environment": settings.app_env,
        "llm_provider": settings.llm_provider,
    }


def main() -> None:
    """개발·운영 공통 ASGI 서버 실행 진입점."""
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
