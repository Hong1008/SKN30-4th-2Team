"""WorkShield MCP transport connection 생성을 검증한다."""

from pathlib import Path

import pytest

from app.config import Settings
from app.llm.mcp.connection import build_workshield_connection
from app.llm.mcp.types import MCPConfigurationError


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "local",
        "llm_provider": "ollama",
        "llm_model": "configured-model",
    }
    values.update(overrides)
    return Settings(**values)


def _mcp_project(tmp_path: Path) -> Path:
    project = tmp_path / "mcp-project"
    (project / "src").mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname='test'\n")
    (project / "src" / "app.py").write_text("print('test')\n")
    return project


def test_builds_streamable_http_connection() -> None:
    connection = build_workshield_connection(
        _settings(
            workshield_mcp_transport="streamable_http",
            workshield_mcp_url="http://mcp.internal:9000/mcp",
            workshield_mcp_timeout=12,
            workshield_mcp_read_timeout=45,
        )
    )

    assert connection == {
        "transport": "streamable_http",
        "url": "http://mcp.internal:9000/mcp",
        "timeout": 12.0,
        "sse_read_timeout": 45.0,
        "terminate_on_close": True,
    }


def test_builds_local_uv_stdio_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = _mcp_project(tmp_path)
    monkeypatch.setattr(
        "app.llm.mcp.connection.shutil.which",
        lambda command: "/usr/bin/uv" if command == "uv" else None,
    )

    connection = build_workshield_connection(
        _settings(
            workshield_mcp_transport="stdio",
            workshield_mcp_project_dir=project,
        )
    )

    assert connection == {
        "transport": "stdio",
        "command": "/usr/bin/uv",
        "args": [
            "run",
            "--project",
            str(project),
            "python",
            str(project / "src" / "app.py"),
        ],
        "cwd": project,
        "env": {
            "PYTHONPATH": str(project / "src"),
            "MCP_TRANSPORT": "stdio",
        },
    }


def test_stdio_requires_uv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = _mcp_project(tmp_path)
    monkeypatch.setattr("app.llm.mcp.connection.shutil.which", lambda command: None)

    with pytest.raises(MCPConfigurationError, match="uv"):
        build_workshield_connection(
            _settings(
                workshield_mcp_transport="stdio",
                workshield_mcp_project_dir=project,
            )
        )


def test_stdio_requires_workshield_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "missing-project"
    project.mkdir()
    monkeypatch.setattr("app.llm.mcp.connection.shutil.which", lambda command: "uv")

    with pytest.raises(MCPConfigurationError, match="pyproject.toml"):
        build_workshield_connection(
            _settings(
                workshield_mcp_transport="stdio",
                workshield_mcp_project_dir=project,
            )
        )
