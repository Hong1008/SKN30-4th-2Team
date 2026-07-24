"""FastAPI 애플리케이션이 공유하는 외부 자원의 수명주기를 관리한다."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db.database import Database
from app.llm.mcp import open_workshield_mcp


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """SQLite와 MCP session을 API 애플리케이션 수명과 함께 관리한다."""
    settings = get_settings()
    database = Database(settings.database_url, echo=settings.database_echo)
    database.create_schema()
    app.state.database = database
    try:
        async with open_workshield_mcp(settings) as runtime:
            app.state.workshield_mcp = runtime
            try:
                yield
            finally:
                del app.state.workshield_mcp
    finally:
        if hasattr(app.state, "database"):
            del app.state.database
        database.dispose()
