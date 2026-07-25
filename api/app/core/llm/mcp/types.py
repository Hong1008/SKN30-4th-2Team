"""WorkShield MCP client가 공유하는 runtime과 오류 타입을 정의한다."""

from dataclasses import dataclass
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp import ClientSession


class MCPConfigurationError(ValueError):
    """MCP transport 또는 로컬 실행 설정이 올바르지 않을 때 발생한다."""


class MCPConnectionError(RuntimeError):
    """MCP transport 연결이나 초기화에 실패했을 때 발생한다."""


class MCPCompatibilityError(RuntimeError):
    """연결한 서버가 WorkShield client 계약을 제공하지 않을 때 발생한다."""


@dataclass(frozen=True, slots=True)
class WorkShieldMCPRuntime:
    """앱 수명 동안 공유하는 WorkShield MCP 연결 세션과 도구 런타임 상태."""

    client: MultiServerMCPClient
    """MCP 서버 연결을 관리하는 클라이언트."""
    session: ClientSession
    """활성화된 MCP 통신 세션."""
    tools: tuple[BaseTool, ...]
    """MCP 서버에서 로드한 LangChain 호환 도구 목록."""
    capabilities: dict[str, object]
    """MCP 서버가 제공하는 기능 및 스펙 정보."""
    supports_file_path: bool
    """로컬 파일 경로 직접 전달 가능 여부 (STDIO 지원)."""
