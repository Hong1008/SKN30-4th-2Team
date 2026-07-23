"""FastAPI에서 재사용할 LLM·MCP 의존성을 정의한다."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool

from app.config import SettingsDep
from app.llm.factory import create_chat_model
from app.llm.mcp.types import WorkShieldMCPRuntime
from app.llm.types import ReasoningMode


def get_chat_model(settings: SettingsDep) -> BaseChatModel:
    """선택 provider의 기본 non-reasoning chat model을 반환한다."""
    return create_chat_model(settings, ReasoningMode.OFF)

def get_mcp_runtime(request: Request) -> WorkShieldMCPRuntime:
    """FastAPI lifespan에서 준비한 WorkShield MCP runtime을 반환한다."""
    runtime = getattr(request.app.state, "workshield_mcp", None)
    if not isinstance(runtime, WorkShieldMCPRuntime):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WorkShield MCP client가 준비되지 않았습니다.",
        )
    return runtime

def get_mcp_tools(runtime: MCPRuntimeDep) -> tuple[BaseTool, ...]:
    """현재 session에 결합된 LangChain MCP 도구를 반환한다."""
    return runtime.tools


ChatModelDep = Annotated[BaseChatModel, Depends(get_chat_model)]
"""FastAPI 라우터와 서비스에서 재사용하는 chat model 의존성."""
MCPRuntimeDep = Annotated[WorkShieldMCPRuntime, Depends(get_mcp_runtime)]
"""MCP session 정보가 필요한 서비스에서 재사용하는 의존성."""
MCPToolsDep = Annotated[tuple[BaseTool, ...], Depends(get_mcp_tools)]
"""LangGraph와 agent 계층에서 재사용하는 MCP 도구 의존성."""
