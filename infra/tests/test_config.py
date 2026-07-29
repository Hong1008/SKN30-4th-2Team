from __future__ import annotations

import json
from pathlib import Path

import pytest

from workshield_infra.config import (
    DeploymentConfig,
    load_secret_file,
    update_secret_file,
)


def _values() -> dict[str, str]:
    return {
        "app_name": "workshield-prod",
        "environment": "prod",
        "aws_account_id": "111122223333",
        "aws_region": "ap-northeast-2",
        "availability_zone": "ap-northeast-2a",
        "origin_domain": "workshield.duckdns.org",
        "acme_email": "infra@example.com",
        "cloudfront_origin_prefix_list_id": "pl-1234",
        "instance_type": "t3.small",
        "github_organization": "example",
        "github_repository": "repository",
        "github_environment": "production",
        "ghcr_owner": "example",
        "nginx_image": f"nginx@sha256:{'0' * 64}",
        "runpod_llm_image": "vllm/vllm-openai:latest",
        "runpod_llm_template_id": "llm-template",
        "runpod_llm_gpu": "NVIDIA A40",
        "runpod_llm_model": "RedHatAI/Qwen3.5-9B-FP8-dynamic",
        "runpod_embed_template_id": "embed-template",
        "runpod_embed_gpu": "NVIDIA RTX 2000 Ada",
        "runpod_embed_image": "ghcr.io/example/mcp/embed-rerank:latest",
    }


def test_config_accepts_complete_public_values(tmp_path: Path) -> None:
    path = tmp_path / "prod.json"
    path.write_text(json.dumps(_values()), encoding="utf-8")

    config = DeploymentConfig.from_file(path)

    assert config.environment == "prod"
    assert config.runpod_embed_image.endswith(":latest")


def test_config_rejects_mutable_nginx_image(tmp_path: Path) -> None:
    values = _values()
    values["nginx_image"] = "nginx:latest"
    path = tmp_path / "prod.json"
    path.write_text(json.dumps(values), encoding="utf-8")

    with pytest.raises(ValueError, match="digest"):
        DeploymentConfig.from_file(path)


def test_config_rejects_llm_model_without_preset(tmp_path: Path) -> None:
    values = _values()
    values["runpod_llm_model"] = "someone/unsupported-model"
    path = tmp_path / "prod.json"
    path.write_text(json.dumps(values), encoding="utf-8")

    with pytest.raises(ValueError, match="지원 preset에 없습니다"):
        DeploymentConfig.from_file(path)


def test_secret_file_is_parsed_without_shell_evaluation(tmp_path: Path) -> None:
    path = tmp_path / "prod.secrets.env"
    path.write_text("TOKEN=$(touch should-not-exist)\nQUOTED='safe value'\n", encoding="utf-8")

    values = load_secret_file(path)

    assert values == {"TOKEN": "$(touch should-not-exist)", "QUOTED": "safe value"}
    assert not (tmp_path / "should-not-exist").exists()


def test_secret_file_update_is_atomic_and_preserves_comments(tmp_path: Path) -> None:
    path = tmp_path / "prod.secrets.env"
    path.write_text(
        "# managed locally\nVLLM_API_KEY=\nORIGIN_HEADER=existing\n",
        encoding="utf-8",
    )
    path.chmod(0o644)

    update_secret_file(
        path,
        {
            "VLLM_API_KEY": "generated-vllm",
            "RUNPOD_EMBED_API_KEY": "generated-embed",
        },
    )

    assert path.read_text(encoding="utf-8") == (
        "# managed locally\n"
        "VLLM_API_KEY=generated-vllm\n"
        "ORIGIN_HEADER=existing\n"
        "\n"
        "RUNPOD_EMBED_API_KEY=generated-embed\n"
    )
    assert path.stat().st_mode & 0o777 == 0o600
