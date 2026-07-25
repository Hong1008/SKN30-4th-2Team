"""FastAPI OpenAPI 스키마 추출 및 docs/api/openapi.json 자동 생성 스크립트."""

import json
import sys
from pathlib import Path

# api 디렉터리를 sys.path에 추가하여 어디서든 실행 가능하도록 처리
api_dir = Path(__file__).resolve().parent.parent
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from main import app  # noqa: E402


def generate_openapi() -> None:
    """FastAPI 앱에서 OpenAPI 3.1 스키마를 추출하여 docs/api/openapi.json 파일로 저장한다."""
    api_dir = Path(__file__).resolve().parent.parent
    output_path = api_dir.parent / "docs" / "api" / "openapi.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    openapi_schema = app.openapi()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"OpenAPI schema generated successfully: {output_path.resolve()}")


if __name__ == "__main__":
    generate_openapi()
