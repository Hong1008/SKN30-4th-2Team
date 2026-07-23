"""docs/api/openapi.json 스키마 생성 및 최신 상태 검증 테스트."""

import json
from pathlib import Path

from main import app


def test_openapi_json_is_up_to_date() -> None:
    """FastAPI OpenAPI 스키마가 docs/api/openapi.json 파일과 일치하는지 검증한다."""
    api_dir = Path(__file__).resolve().parent.parent
    openapi_file = api_dir.parent / "docs" / "api" / "openapi.json"

    current_schema = app.openapi()

    assert openapi_file.exists(), f"OpenAPI schema file does not exist: {openapi_file}"

    saved_schema = json.loads(openapi_file.read_text(encoding="utf-8"))
    assert current_schema == saved_schema, (
        "docs/api/openapi.json이 현재 FastAPI 스키마와 일치하지 않습니다. "
        "'uv run python scripts/generate_openapi.py'를 실행하여 최신화하세요."
    )
