"""실제 v1 Router의 Cookie 소유권과 세션·검토 흐름을 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from pypdf import PdfWriter

from app.api.v1.router import router as v1_router
from app.common.exception_handlers import register_exception_handlers
from app.config import Settings, get_settings
from app.db.database import Database
from app.db.dependencies import get_database
from app.llm.mcp.dependencies import get_workshield_runtime
from app.storage.dependencies import get_file_storage
from app.storage.local import LocalFileStorage


class FakeTool:
    """범위 판별 MCP 도구를 흉내 내는 테스트 도구."""

    name = "assess_contract_scope"

    def __init__(
        self,
        payload: dict[str, object] | None = None,
        *,
        delay: float = 0,
    ) -> None:
        self.payload = payload or {
            "scope_status": "CONTRACT_TYPE_UNCERTAIN",
            "suggested_contract_type": "SW_FREELANCE",
            "candidates": [],
        }
        self.delay = delay
        self.call_count = 0

    async def ainvoke(self, _payload: dict[str, object]) -> dict[str, object]:
        self.call_count += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.payload


def create_test_app(
    tmp_path: Path,
    scope_payload: dict[str, object] | None = None,
    *,
    max_upload_size_bytes: int = 10 * 1024 * 1024,
    scope_delay: float = 0,
    workshield_mcp_timeout: float = 30,
) -> FastAPI:
    """실제 v1 Router에 테스트 의존성만 교체한 앱을 만든다."""
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    database.create_schema()
    storage = LocalFileStorage(tmp_path / "uploads")
    settings = Settings(
        app_env="local",
        llm_provider="ollama",
        temp_upload_dir=tmp_path / "uploads",
        max_upload_size_bytes=max_upload_size_bytes,
        workshield_mcp_timeout=workshield_mcp_timeout,
    )
    fake_tool = FakeTool(scope_payload, delay=scope_delay)
    runtime = SimpleNamespace(tools=(fake_tool,), supports_file_path=False)

    @asynccontextmanager
    async def no_lifespan(_app: FastAPI):
        yield

    app = FastAPI(lifespan=no_lifespan)
    register_exception_handlers(app)
    app.include_router(v1_router)
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_file_storage] = lambda: storage
    app.dependency_overrides[get_workshield_runtime] = lambda: runtime
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.fake_scope_tool = fake_tool
    app.state.test_storage = storage
    return app


pytestmark = pytest.mark.asyncio


def _pdf(*, encrypted: bool = False) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("secret")
    writer.write(output)
    return output.getvalue()


async def test_session_creation_and_review_access_are_cookie_bound(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    pdf = _pdf()

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as owner:
        created = await owner.post(
            "/api/v1/review-sessions",
            files={"file": ("contract.pdf", pdf, "application/pdf")},
        )
        assert created.status_code == 201
        assert "workshield_session=" in created.headers["set-cookie"]
        session_id = created.json()["data"]["session_id"]

        state = await owner.get(f"/api/v1/review-sessions/{session_id}")
        assert state.status_code == 200

        selected = await owner.patch(
            f"/api/v1/review-sessions/{session_id}/contract-type",
            json={
                "selected_contract_type": "SW_FREELANCE",
                "selection_source": "MANUAL",
            },
        )
        assert selected.status_code == 200

        review = await owner.post(
            "/api/v1/reviews",
            json={"session_id": session_id},
            headers={"Idempotency-Key": "route-test-1"},
        )
        assert review.status_code == 202
        review_id = review.json()["data"]["review_id"]
        status = await owner.get(f"/api/v1/reviews/{review_id}")
        assert status.status_code == 200

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as other:
        assert (
            await other.get(f"/api/v1/review-sessions/{session_id}")
        ).status_code == 404
        assert (await other.get(f"/api/v1/reviews/{review_id}")).status_code == 404


@pytest.mark.parametrize(
    ("scope_status", "review_state", "allowed_actions"),
    [
        ("IN_SCOPE", "TYPE_SELECTION_REQUIRED", ["SELECT_CONTRACT_TYPE"]),
        (
            "CONTRACT_TYPE_UNCERTAIN",
            "TYPE_SELECTION_REQUIRED",
            ["SELECT_CONTRACT_TYPE"],
        ),
        (
            "OUT_OF_SCOPE",
            "OUT_OF_SCOPE_CONFIRMATION_REQUIRED",
            ["SELECT_CONTRACT_TYPE", "CONFIRM_OUT_OF_SCOPE"],
        ),
        ("EMPTY_DOCUMENT", "REUPLOAD_REQUIRED", ["REUPLOAD"]),
    ],
)
async def test_scope_statuses_drive_product_session_state(
    tmp_path: Path,
    scope_status: str,
    review_state: str,
    allowed_actions: list[str],
) -> None:
    app = create_test_app(
        tmp_path,
        {
            "status": scope_status,
            "suggested_contract_type": "SW_FREELANCE",
            "candidates": [
                {"contract_type": "SW_FREELANCE", "score": 82},
            ],
            "matched_clause_count": 3,
            "exclusion_markers": None,
            "message": "상태 안내",
        },
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/review-sessions",
            files={"file": ("contract.pdf", _pdf(), "application/pdf")},
        )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["scope_status"] == scope_status
    assert data["review_state"] == review_state
    assert data["allowed_actions"] == allowed_actions
    assert data["candidates"] == [
        {"contract_type": "SW_FREELANCE", "evidence_score": 82},
    ]
    assert data["matched_clause_count"] == 3
    assert data["scope_message"] == "상태 안내"


@pytest.mark.parametrize(
    ("file_name", "content", "status_code", "error_code"),
    [
        ("contract.exe", b"binary", 415, "UNSUPPORTED_FILE_TYPE"),
        ("contract.docx", b"not-a-zip", 415, "FILE_TYPE_MISMATCH"),
        ("contract.pdf", b"%PDF-1.4\nbroken", 422, "CORRUPTED_FILE"),
        ("encrypted.pdf", _pdf(encrypted=True), 422, "ENCRYPTED_FILE"),
    ],
)
async def test_invalid_files_are_blocked_before_mcp_call(
    tmp_path: Path,
    file_name: str,
    content: bytes,
    status_code: int,
    error_code: str,
) -> None:
    app = create_test_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/review-sessions",
            files={"file": (file_name, content, "application/octet-stream")},
        )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    assert app.state.fake_scope_tool.call_count == 0
    assert list(app.state.test_storage.list_keys()) == []


async def test_oversized_file_is_blocked_before_mcp_call(tmp_path: Path) -> None:
    app = create_test_app(tmp_path, max_upload_size_bytes=10)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/review-sessions",
            files={"file": ("contract.pdf", b"x" * 11, "application/pdf")},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert app.state.fake_scope_tool.call_count == 0


async def test_invalid_mcp_scope_response_removes_saved_file(tmp_path: Path) -> None:
    app = create_test_app(
        tmp_path,
        {
            "status": "IN_SCOPE",
            "candidates": [{"contract_type": "SW_FREELANCE", "score": None}],
        },
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/review-sessions",
            files={"file": ("contract.pdf", _pdf(), "application/pdf")},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MCP_RESPONSE_INVALID"
    assert app.state.fake_scope_tool.call_count == 1
    assert list(app.state.test_storage.list_keys()) == []


async def test_mcp_scope_timeout_returns_504_and_removes_saved_file(
    tmp_path: Path,
) -> None:
    app = create_test_app(
        tmp_path,
        scope_delay=0.1,
        workshield_mcp_timeout=0.01,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/review-sessions",
            files={"file": ("contract.pdf", _pdf(), "application/pdf")},
        )

    assert response.status_code == 504
    assert response.json()["error"] == {
        "code": "MCP_TIMEOUT",
        "message": "계약 범위 분석 시간이 초과되었습니다.",
        "field": None,
        "retryable": True,
        "next_action": "RETRY",
        "details": {},
    }
    assert app.state.fake_scope_tool.call_count == 1
    assert list(app.state.test_storage.list_keys()) == []


async def test_out_of_scope_requires_type_selection_and_confirmation(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path, {"status": "OUT_OF_SCOPE"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/api/v1/review-sessions",
            files={"file": ("contract.pdf", _pdf(), "application/pdf")},
        )
        session_id = created.json()["data"]["session_id"]
        confirmed = await client.post(
            f"/api/v1/review-sessions/{session_id}/out-of-scope-confirmation",
            json={"confirmed": True},
        )
        assert confirmed.json()["data"]["can_start_review"] is False

        selected = await client.patch(
            f"/api/v1/review-sessions/{session_id}/contract-type",
            json={
                "selected_contract_type": "SW_FREELANCE",
                "selection_source": "MANUAL",
            },
        )

    assert selected.status_code == 200
    assert selected.json()["data"]["can_start_review"] is True


async def test_empty_document_and_inactive_type_cannot_start_review(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path, {"status": "EMPTY_DOCUMENT"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/api/v1/review-sessions",
            files={"file": ("contract.pdf", _pdf(), "application/pdf")},
        )
        session_id = created.json()["data"]["session_id"]
        empty_selection = await client.patch(
            f"/api/v1/review-sessions/{session_id}/contract-type",
            json={
                "selected_contract_type": "SW_FREELANCE",
                "selection_source": "MANUAL",
            },
        )
        inactive_selection = await client.patch(
            f"/api/v1/review-sessions/{session_id}/contract-type",
            json={
                "selected_contract_type": "OTHER_CONTRACT",
                "selection_source": "MANUAL",
            },
        )

    assert empty_selection.status_code == 409
    assert inactive_selection.status_code == 422
    assert inactive_selection.json()["error"]["code"] == "UNSUPPORTED_CONTRACT_TYPE"
