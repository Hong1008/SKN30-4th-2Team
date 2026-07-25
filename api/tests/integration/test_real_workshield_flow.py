"""실제 WorkShield MCP와 API 세션·Review 경계를 검증한다.

기본 테스트에서는 외부 프로세스를 실행하지 않는다. 월요일 연동 검증처럼
명시적으로 환경변수를 설정한 경우에만 실제 MCP와 테스트 계약서를 사용한다.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

import app.factory as factory_module
import app.lifespan as lifespan_module
from app.config import MCPTransport, Settings, get_settings
from app.factory import create_app


pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
REQUIRED_MCP_TOOLS = {
    "get_mcp_capabilities",
    "list_contract_types",
    "list_categories",
    "list_toxic_pattern_details",
    "assess_contract_scope",
    "review_contract_candidates",
    "get_category_grounding",
}
PRODUCT_EXTENSIONS = {"hwp", "hwpx", "pdf", "docx"}


def _require_flag(name: str) -> None:
    if os.getenv(name) != "1":
        pytest.skip(f"{name}=1일 때만 실제 WorkShield 연동 테스트를 실행합니다.")


def _integration_file() -> Path:
    raw_path = os.getenv("WORKSHIELD_INTEGRATION_FILE")
    if not raw_path:
        pytest.skip("WORKSHIELD_INTEGRATION_FILE에 테스트 계약서 경로가 필요합니다.")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        pytest.fail(f"통합 테스트 계약서를 찾을 수 없습니다: {path}")
    if path.suffix.lower().removeprefix(".") not in PRODUCT_EXTENSIONS:
        pytest.fail("통합 테스트 파일은 HWP, HWPX, PDF, DOCX만 사용할 수 있습니다.")
    return path


def _settings(tmp_path: Path) -> Settings:
    transport = MCPTransport(
        os.getenv("WORKSHIELD_MCP_TRANSPORT", MCPTransport.STDIO.value)
    )
    return Settings(
        app_env="local",
        llm_provider="ollama",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'integration.db'}",
        temp_upload_dir=tmp_path / "uploads",
        workshield_mcp_transport=transport,
        workshield_mcp_url=os.getenv(
            "WORKSHIELD_MCP_URL",
            "http://localhost:8000/mcp",
        ),
        workshield_mcp_project_dir=Path(
            os.getenv(
                "WORKSHIELD_MCP_PROJECT_DIR",
                str(Path(__file__).resolve().parents[3] / "mcp"),
            )
        ),
        workshield_mcp_timeout=float(os.getenv("WORKSHIELD_MCP_TIMEOUT", "30")),
        workshield_mcp_read_timeout=float(
            os.getenv("WORKSHIELD_MCP_READ_TIMEOUT", "300")
        ),
    )


@asynccontextmanager
async def _real_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(factory_module, "get_settings", lambda: settings)
    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    async with app.router.lifespan_context(app):
        yield app


def _assert_common_response(response: httpx.Response) -> dict[str, object]:
    assert response.status_code < 400, response.text
    payload = response.json()
    assert isinstance(payload.get("data"), dict), payload
    return payload["data"]


async def test_real_mcp_be_a_session_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실제 MCP metadata·범위 분석과 익명 세션 격리를 검증한다."""
    _require_flag("RUN_WORKSHIELD_INTEGRATION")
    contract_path = _integration_file()

    async with _real_api(tmp_path, monkeypatch) as app:
        runtime = app.state.workshield_mcp
        tool_names = {tool.name for tool in runtime.tools}
        assert REQUIRED_MCP_TOOLS <= tool_names
        assert runtime.supports_file_path is (
            _settings(tmp_path).workshield_mcp_transport is MCPTransport.STDIO
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as owner:
            metadata_response = await owner.get("/api/v1/metadata")
            metadata = _assert_common_response(metadata_response)
            assert metadata["file_policy"]["extensions"] == [
                "hwp",
                "hwpx",
                "pdf",
                "docx",
            ]
            assert metadata_response.headers["etag"]

            created_response = await owner.post(
                "/api/v1/review-sessions",
                files={
                    "file": (
                        contract_path.name,
                        contract_path.read_bytes(),
                        "application/octet-stream",
                    )
                },
            )
            created = _assert_common_response(created_response)
            assert "HttpOnly" in created_response.headers["set-cookie"]
            assert "workshield_session" not in created_response.text
            assert created["scope_status"] in {
                "IN_SCOPE",
                "CONTRACT_TYPE_UNCERTAIN",
                "OUT_OF_SCOPE",
                "EMPTY_DOCUMENT",
            }
            session_id = str(created["session_id"])

            restored = await owner.get(f"/api/v1/review-sessions/{session_id}")
            assert restored.status_code == 200

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as other_browser:
            denied = await other_browser.get(f"/api/v1/review-sessions/{session_id}")
            assert denied.status_code == 404


async def _prepare_review(
    client: httpx.AsyncClient,
    contract_path: Path,
) -> tuple[str, str]:
    created_response = await client.post(
        "/api/v1/review-sessions",
        files={
            "file": (
                contract_path.name,
                contract_path.read_bytes(),
                "application/octet-stream",
            )
        },
    )
    created = _assert_common_response(created_response)
    if created["scope_status"] == "EMPTY_DOCUMENT":
        pytest.skip(
            "테스트 문서가 EMPTY_DOCUMENT여서 실제 Review를 시작할 수 없습니다."
        )
    session_id = str(created["session_id"])
    selected = await client.patch(
        f"/api/v1/review-sessions/{session_id}/contract-type",
        json={
            "selected_contract_type": "SW_FREELANCE",
            "selection_source": "MANUAL",
        },
    )
    _assert_common_response(selected)
    if created["scope_status"] == "OUT_OF_SCOPE":
        confirmed = await client.post(
            f"/api/v1/review-sessions/{session_id}/out-of-scope-confirmation",
            json={"confirmed": True},
        )
        _assert_common_response(confirmed)

    started = await client.post(
        "/api/v1/reviews",
        json={"session_id": session_id},
        headers={"Idempotency-Key": "real-mcp-review-1"},
    )
    started_data = _assert_common_response(started)
    return session_id, str(started_data["review_id"])


async def _wait_for_terminal_review(
    client: httpx.AsyncClient,
    review_id: str,
) -> dict[str, object]:
    timeout_seconds = float(os.getenv("WORKSHIELD_REVIEW_WAIT_SECONDS", "300"))
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = await client.get(f"/api/v1/reviews/{review_id}")
        data = _assert_common_response(response)
        if data["review_state"] in {"COMPLETED", "FAILED"}:
            return data
        await asyncio.sleep(0.5)
    pytest.fail(f"실제 Review가 {timeout_seconds}초 안에 종료되지 않았습니다.")


async def test_real_mcp_be_b_review_and_sse_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BE-B 담당 Review·결과·SSE가 공통 세션 경계에서 동작하는지 검증한다."""
    _require_flag("RUN_WORKSHIELD_REVIEW_INTEGRATION")
    contract_path = _integration_file()

    async with _real_api(tmp_path, monkeypatch) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as owner:
            _, review_id = await _prepare_review(owner, contract_path)
            terminal = await _wait_for_terminal_review(owner, review_id)

            events = await owner.get(
                f"/api/v1/reviews/{review_id}/events",
                headers={"Last-Event-ID": "0"},
            )
            assert events.status_code == 200
            assert f'"review_id": "{review_id}"' in events.text
            assert (
                "event: completed" in events.text
                if terminal["review_state"] == "COMPLETED"
                else "event: failed" in events.text
            )

            if terminal["review_state"] == "COMPLETED":
                results = await owner.get(f"/api/v1/reviews/{review_id}/results")
                result_data = _assert_common_response(results)
                assert isinstance(result_data["clause_results"], list)
                assert isinstance(
                    result_data["missing_standard_clauses"],
                    list,
                )
                assert all(
                    isinstance(item["toxic_patterns"], list)
                    for item in result_data["clause_results"]
                )

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as other_browser:
            assert (
                await other_browser.get(f"/api/v1/reviews/{review_id}")
            ).status_code == 404
            assert (
                await other_browser.get(f"/api/v1/reviews/{review_id}/events")
            ).status_code == 404
