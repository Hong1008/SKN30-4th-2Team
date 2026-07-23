"""설정에서 WorkShield MCP transport connection을 생성한다."""

import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

from langchain_mcp_adapters.sessions import (
    StdioConnection,
    StreamableHttpConnection,
)

from app.config import API_ROOT, MCPTransport, Settings
from app.llm.mcp.types import MCPConfigurationError


def _absolute_project_dir(project_dir: Path) -> Path:
    """상대 MCP 프로젝트 경로를 API 프로젝트 기준 절대경로로 바꾼다."""
    if project_dir.is_absolute():
        return project_dir.resolve()
    return (API_ROOT / project_dir).resolve()


def _build_stdio_connection(
    command: str,
    args: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> StdioConnection:
    """shell을 거치지 않는 stdio connection을 조립한다."""
    return {
        "transport": "stdio",
        "command": command,
        "args": list(args),
        "cwd": cwd,
        "env": dict(env),
    }


def _build_local_uv_connection(settings: Settings) -> StdioConnection:
    """독립 uv 환경에서 로컬 WorkShield MCP 서버를 실행한다."""
    project_dir = _absolute_project_dir(settings.workshield_mcp_project_dir)
    pyproject = project_dir / "pyproject.toml"
    entrypoint = project_dir / "src" / "app.py"
    source_dir = project_dir / "src"
    uv_command = shutil.which("uv")

    if uv_command is None:
        raise MCPConfigurationError("stdio MCP 실행에 필요한 uv를 찾을 수 없습니다.")
    if not pyproject.is_file():
        raise MCPConfigurationError(
            f"WorkShield MCP pyproject.toml을 찾을 수 없습니다: {pyproject}"
        )
    if not entrypoint.is_file():
        raise MCPConfigurationError(
            f"WorkShield MCP 진입점을 찾을 수 없습니다: {entrypoint}"
        )

    return _build_stdio_connection(
        uv_command,
        (
            "run",
            "--project",
            str(project_dir),
            "python",
            str(entrypoint),
        ),
        cwd=project_dir,
        env={
            "PYTHONPATH": str(source_dir),
            "MCP_TRANSPORT": "stdio",
        },
    )


def build_workshield_connection(
    settings: Settings,
) -> StreamableHttpConnection | StdioConnection:
    """선택된 transport에 맞는 WorkShield MCP connection을 반환한다."""
    if settings.workshield_mcp_transport is MCPTransport.STREAMABLE_HTTP:
        return {
            "transport": "streamable_http",
            "url": str(settings.workshield_mcp_url),
            "timeout": settings.workshield_mcp_timeout,
            "sse_read_timeout": settings.workshield_mcp_read_timeout,
            "terminate_on_close": True,
        }
    if settings.workshield_mcp_transport is MCPTransport.STDIO:
        return _build_local_uv_connection(settings)
    raise MCPConfigurationError(
        f"지원하지 않는 MCP transport입니다: {settings.workshield_mcp_transport}"
    )
