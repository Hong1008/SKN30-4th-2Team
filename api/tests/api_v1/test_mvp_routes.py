"""MVP metadata·review·grounding·chat·suggestions 통합 흐름."""

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
from app.llm.dependencies import get_chat_model
from app.llm.mcp.dependencies import get_workshield_runtime
from app.storage.dependencies import get_file_storage
from app.storage.local import LocalFileStorage


class FakeTool:
    def __init__(self, name: str, payload: dict[str, object], calls: dict[str, int]):
        self.name = name
        self._payload = payload
        self._calls = calls

    async def ainvoke(self, _payload: dict[str, object]) -> dict[str, object]:
        self._calls[self.name] = self._calls.get(self.name, 0) + 1
        return self._payload


class FakeStructuredRunnable:
    def __init__(self, schema: type) -> None:
        self._schema = schema

    async def ainvoke(self, _prompt: str):
        if self._schema.__name__ == "ChatStructuredOutput":
            return {
                "outcome": "ANSWERED",
                "answer": "현재 검토 결과에서는 책임 범위를 추가로 확인할 수 있습니다.",
                "sources": [{"type": "USER_CLAUSE", "id": "uc_1"}],
                "limitations": ["법률 자문이 아닙니다."],
            }
        return {
            "outcome": "GENERATED",
            "text": "책임 범위는 당사자가 확인한 기준으로 협의합니다.",
            "key_changes": ["책임 범위 확인"],
            "standard_clause_ids": ["std_1"],
            "grounding_source_ids": ["law_1"],
            "required_confirmations": [],
        }


class FakeChatModel:
    def with_structured_output(self, schema: type):
        return FakeStructuredRunnable(schema)


def create_mvp_app(tmp_path: Path) -> tuple[FastAPI, dict[str, int]]:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'mvp.db'}")
    database.create_schema()
    storage = LocalFileStorage(tmp_path / "uploads")
    settings = Settings(
        app_env="local",
        llm_provider="ollama",
        llm_model="test",
        temp_upload_dir=tmp_path / "uploads",
    )
    calls: dict[str, int] = {}
    tools = (
        FakeTool(
            "assess_contract_scope",
            {
                "scope_status": "CONTRACT_TYPE_UNCERTAIN",
                "suggested_contract_type": "SW_FREELANCE",
                "candidates": [],
            },
            calls,
        ),
        FakeTool(
            "review_contract_candidates",
            {
                "status": "OK",
                "contract_type": "SW_FREELANCE",
                "clause_results": [
                    {
                        "user_clause": {"id": "uc_1", "text": "책임 조항"},
                        "match": {
                            "status": "CANDIDATE_SELECTED",
                            "standard": {
                                "clause_id": "std_1",
                                "category": "LIABILITY",
                                "text": "표준 책임 조항",
                            },
                        },
                    }
                ],
                "missing_standard_clauses": [],
                "toxic_patterns": [],
            },
            calls,
        ),
        FakeTool(
            "get_category_grounding",
            {
                "status": "OK",
                "category": {"code": "LIABILITY", "label": "책임·손해배상"},
                "grounding": [
                    {
                        "source_id": "law_1",
                        "law_name": "민법",
                        "article": "제390조",
                        "text": "채무불이행과 손해배상에 관한 참고 조문",
                        "source": "국가법령정보센터",
                    }
                ],
            },
            calls,
        ),
        FakeTool(
            "list_contract_types",
            {
                "contract_types": [
                    {"code": "SW_FREELANCE", "label": "SW 프리랜서 용역"}
                ]
            },
            calls,
        ),
        FakeTool(
            "list_categories",
            {"categories": [{"code": "LIABILITY", "label": "책임·손해배상"}]},
            calls,
        ),
        FakeTool(
            "list_toxic_pattern_details",
            {"toxic_patterns": [{"code": "UNILATERAL_CHANGE", "label": "일방 변경"}]},
            calls,
        ),
    )
    runtime = SimpleNamespace(tools=tools, supports_file_path=False)

    @asynccontextmanager
    async def no_lifespan(_app: FastAPI):
        yield

    app = FastAPI(lifespan=no_lifespan)
    register_exception_handlers(app)
    app.include_router(v1_router)
    app.state.review_tasks = {}
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_file_storage] = lambda: storage
    app.dependency_overrides[get_workshield_runtime] = lambda: runtime
    app.dependency_overrides[get_chat_model] = lambda: FakeChatModel()
    app.dependency_overrides[get_settings] = lambda: settings
    return app, calls


async def _wait_completed(client: httpx.AsyncClient, review_id: str) -> None:
    for _ in range(100):
        response = await client.get(f"/api/v1/reviews/{review_id}")
        if response.json()["data"]["review_state"] == "COMPLETED":
            return
        await asyncio.sleep(0.01)
    raise AssertionError("review did not complete")


pytestmark = pytest.mark.asyncio


def _pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)
    return output.getvalue()


async def test_full_mvp_flow_and_browser_isolation(tmp_path: Path) -> None:
    app, _ = create_mvp_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as owner:
        created = await owner.post(
            "/api/v1/review-sessions",
            files={
                "file": (
                    "contract.pdf",
                    _pdf(),
                    "application/pdf",
                )
            },
        )
        session_id = created.json()["data"]["session_id"]
        await owner.patch(
            f"/api/v1/review-sessions/{session_id}/contract-type",
            json={
                "selected_contract_type": "SW_FREELANCE",
                "selection_source": "MANUAL",
            },
        )
        started = await owner.post(
            "/api/v1/reviews",
            json={"session_id": session_id},
            headers={"Idempotency-Key": "create-1"},
        )
        assert started.status_code == 202
        review_id = started.json()["data"]["review_id"]
        replay = await owner.post(
            "/api/v1/reviews",
            json={"session_id": session_id},
            headers={"Idempotency-Key": "create-1"},
        )
        assert replay.json()["data"]["review_id"] == review_id
        await _wait_completed(owner, review_id)

        result = await owner.get(f"/api/v1/reviews/{review_id}/results")
        assert result.json()["data"]["result"]["clause_results"][0]["user_clause"][
            "id"
        ] == "uc_1"
        grounding = await owner.get(
            f"/api/v1/reviews/{review_id}/grounding",
            params={"category": "LIABILITY"},
        )
        assert grounding.json()["data"]["grounding_status"] == "OK"

        chat = await owner.post(
            f"/api/v1/reviews/{review_id}/chat/messages",
            json={"message": "책임 조항을 설명해줘", "focus_clause_id": "uc_1"},
            headers={"Idempotency-Key": "chat-1"},
        )
        assert chat.json()["data"]["outcome"] == "ANSWERED"
        chat_conflict = await owner.post(
            f"/api/v1/reviews/{review_id}/chat/messages",
            json={"message": "다른 질문", "focus_clause_id": "uc_1"},
            headers={"Idempotency-Key": "chat-1"},
        )
        assert chat_conflict.status_code == 409
        assert chat_conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

        suggestion = await owner.post(
            f"/api/v1/reviews/{review_id}/suggestions",
            json={
                "user_clause_id": "uc_1",
                "purpose": "책임 범위를 명확히 하기",
            },
            headers={"Idempotency-Key": "suggestion-1"},
        )
        assert suggestion.json()["data"]["outcome"] == "GENERATED"
        events = await owner.get(
            f"/api/v1/reviews/{review_id}/events",
            headers={"Last-Event-ID": "0"},
        )
        assert "event: completed" in events.text
        first_cancel = await owner.delete(f"/api/v1/reviews/{review_id}")
        second_cancel = await owner.delete(f"/api/v1/reviews/{review_id}")
        assert first_cancel.json()["data"]["review_state"] == "CANCELLED"
        assert second_cancel.status_code == 200
        assert second_cancel.json()["data"]["deleted"] is False

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as other:
        assert (
            await other.get(
                f"/api/v1/reviews/{review_id}/grounding",
                params={"category": "LIABILITY"},
            )
        ).status_code == 404
        assert (
            await other.post(
                f"/api/v1/reviews/{review_id}/chat/messages",
                json={"message": "조회"},
                headers={"Idempotency-Key": "other-chat"},
            )
        ).status_code == 404


async def test_metadata_cache_and_etag(tmp_path: Path) -> None:
    app, calls = create_mvp_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        first = await client.get("/api/v1/metadata")
        second = await client.get("/api/v1/metadata")
        not_modified = await client.get(
            "/api/v1/metadata",
            headers={"If-None-Match": first.headers["etag"]},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert not_modified.status_code == 304
    assert calls["list_contract_types"] == 1
    assert calls["list_categories"] == 1
    assert calls["list_toxic_pattern_details"] == 1
    enabled = {
        item["code"]
        for item in first.json()["data"]["contract_types"]
        if item["enabled_for_mvp"]
    }
    assert enabled == {"SW_FREELANCE", "SI_SUBCONTRACT", "SM_SUBCONTRACT"}
