"""실제 LangChain MCP 도구 반환 형태의 공통 파싱을 검증한다."""

from types import SimpleNamespace

import pytest

from app.common.errors import ExternalServiceError
from app.review_sessions.service import _tool_payload


def test_extracts_langchain_list_text_content() -> None:
    result = [
        {
            "type": "text",
            "text": '{"status":"IN_SCOPE","candidates":[]}',
            "id": "lc_test",
        }
    ]

    assert _tool_payload(result) == {
        "status": "IN_SCOPE",
        "candidates": [],
    }


def test_extracts_mcp_structured_content() -> None:
    result = SimpleNamespace(
        structuredContent={"status": "OK"},
        content=[],
    )

    assert _tool_payload(result) == {"status": "OK"}


def test_skips_non_json_content_and_rejects_missing_payload() -> None:
    result = [
        {"type": "text", "text": "not-json"},
        {"type": "image", "data": "..."},
    ]

    with pytest.raises(ExternalServiceError) as exc_info:
        _tool_payload(result)

    assert exc_info.value.code == "MCP_RESPONSE_INVALID"
