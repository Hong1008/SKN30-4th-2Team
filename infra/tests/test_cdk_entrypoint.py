import json
from pathlib import Path


INFRA_ROOT = Path(__file__).resolve().parents[1]


def test_cdk_app_uses_cross_platform_uv_launcher() -> None:
    cdk_config = json.loads((INFRA_ROOT / "cdk.json").read_text(encoding="utf-8"))

    assert cdk_config["app"] == "uv run --project . python cdk_app.py"
    assert (INFRA_ROOT / "cdk_app.py").is_file()
