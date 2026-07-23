"""WorkShield MCP client와 persistent session 수명주기를 관리한다."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp.types import CallToolResult

from app.config import MCPTransport, Settings
from app.llm.mcp.connection import build_workshield_connection
from app.llm.mcp.types import (
    MCPCompatibilityError,
    MCPConfigurationError,
    MCPConnectionError,
    WorkShieldMCPRuntime,
)


WORKSHIELD_SERVER_NAME = "workshield"
CAPABILITIES_TOOL_NAME = "get_mcp_capabilities"


def create_workshield_mcp_client(settings: Settings) -> MultiServerMCPClient:
    """설정된 단일 WorkShield 서버를 가리키는 MCP client를 만든다."""
    connection = build_workshield_connection(settings)
    return MultiServerMCPClient(
        {WORKSHIELD_SERVER_NAME: connection},
        handle_tool_errors=True,
    )


def _structured_capabilities(result: CallToolResult) -> dict[str, object]:
    """capabilities 도구 응답을 검증해 구조화 결과만 반환한다."""
    if result.isError:
        raise MCPCompatibilityError(
            "WorkShield MCP capabilities 조회가 오류를 반환했습니다."
        )
    structured = result.structuredContent
    if not isinstance(structured, dict):
        raise MCPCompatibilityError(
            "WorkShield MCP capabilities에 구조화 응답이 없습니다."
        )
    return structured


@asynccontextmanager
async def open_workshield_mcp(
    settings: Settings,
) -> AsyncIterator[WorkShieldMCPRuntime]:
    """MCP session을 열고 같은 session에 결합된 도구를 앱 수명 동안 제공한다."""
    try:
        client = create_workshield_mcp_client(settings)
    except MCPConfigurationError:
        raise
    except (TypeError, ValueError) as error:
        raise MCPConfigurationError(
            "WorkShield MCP client 설정이 유효하지 않습니다."
        ) from error

    stack = AsyncExitStack()
    try:
        session = await stack.enter_async_context(
            client.session(WORKSHIELD_SERVER_NAME)
        )
        tools = await load_mcp_tools(
            session,
            server_name=WORKSHIELD_SERVER_NAME,
            handle_tool_errors=True,
        )
        tool_names = {tool.name for tool in tools}
        if CAPABILITIES_TOOL_NAME not in tool_names:
            raise MCPCompatibilityError(
                "연결한 MCP 서버에 get_mcp_capabilities 도구가 없습니다."
            )

        result = await session.call_tool(CAPABILITIES_TOOL_NAME, {})
        capabilities = _structured_capabilities(result)
    except (MCPCompatibilityError, MCPConfigurationError):
        await stack.aclose()
        raise
    except Exception as error:
        await stack.aclose()
        raise MCPConnectionError(
            "WorkShield MCP 서버 연결 또는 초기화에 실패했습니다."
        ) from error

    try:
        yield WorkShieldMCPRuntime(
            client=client,
            session=session,
            tools=tuple(tools),
            capabilities=capabilities,
            supports_file_path=(
                settings.workshield_mcp_transport is MCPTransport.STDIO
            ),
        )
    finally:
        await stack.aclose()
