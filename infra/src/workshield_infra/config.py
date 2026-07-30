"""비밀이 아닌 배포 대상 설정을 읽고 검증한다."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from workshield_infra.llm_presets import resolve_model_preset


@dataclass(frozen=True, slots=True)
class DeploymentConfig:
    """CDK synth에 필요한 공개 배포 식별자."""

    app_name: str
    environment: str
    aws_account_id: str
    aws_region: str
    availability_zone: str
    origin_domain: str
    acme_email: str
    cloudfront_origin_prefix_list_id: str
    instance_type: str
    github_organization: str

    github_repository: str
    github_environment: str
    ghcr_owner: str
    nginx_image: str
    runpod_llm_image: str
    runpod_llm_template_id: str
    runpod_llm_gpu: str
    runpod_llm_model: str
    runpod_embed_template_id: str
    runpod_embed_gpu: str
    runpod_embed_image: str

    @classmethod
    def from_file(cls, path: Path) -> "DeploymentConfig":
        """JSON 설정 파일을 읽어 누락된 필수 식별자를 빠르게 실패시킨다."""
        values = json.loads(path.read_text(encoding="utf-8"))
        required = {
            "app_name",
            "environment",
            "aws_account_id",
            "aws_region",
            "availability_zone",
            "origin_domain",
            "acme_email",
            "cloudfront_origin_prefix_list_id",
            "instance_type",
            "github_organization",
            "github_repository",
            "github_environment",
            "ghcr_owner",
            "nginx_image",
            "runpod_llm_image",
            "runpod_llm_template_id",
            "runpod_llm_gpu",
            "runpod_llm_model",
            "runpod_embed_template_id",
            "runpod_embed_gpu",
            "runpod_embed_image",
        }
        missing = sorted(required - values.keys())
        if missing:
            raise ValueError(f"배포 설정에 필수 값이 없습니다: {', '.join(missing)}")
        if not values["aws_account_id"].isdigit() or len(values["aws_account_id"]) != 12:
            raise ValueError("aws_account_id는 12자리 숫자여야 합니다.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,40}", values["app_name"]):
            raise ValueError("app_name 형식이 잘못되었습니다.")
        if not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", values["aws_region"]):
            raise ValueError("aws_region 형식이 잘못되었습니다.")
        if not values["availability_zone"].startswith(values["aws_region"]):
            raise ValueError("availability_zone이 aws_region과 일치하지 않습니다.")
        if not values["cloudfront_origin_prefix_list_id"].startswith("pl-"):
            raise ValueError("cloudfront_origin_prefix_list_id는 pl-로 시작해야 합니다.")
        if values["environment"] != "prod":
            raise ValueError("현재 공식 지원 environment는 prod입니다.")
        if not re.fullmatch(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            values["acme_email"],
        ):
            raise ValueError("acme_email은 origin 인증서 알림을 받을 주소여야 합니다.")
        if not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.duckdns\.org",
            values["origin_domain"],
        ):
            raise ValueError("origin_domain은 DuckDNS hostname이어야 합니다.")
        if not re.fullmatch(r"nginx@sha256:[0-9a-f]{64}", values["nginx_image"]):
            raise ValueError("nginx_image는 digest로 고정해야 합니다.")
        for field in (
            "github_organization",
            "github_repository",
            "github_environment",
            "ghcr_owner",
            "runpod_llm_template_id",
            "runpod_embed_template_id",
        ):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,99}", values[field]):
                raise ValueError(f"{field} 형식이 잘못되었습니다.")
        if not re.fullmatch(r"[a-z0-9.]+", values["instance_type"]):
            raise ValueError("instance_type 형식이 잘못되었습니다.")
        if not values["runpod_embed_image"].endswith(":latest"):
            raise ValueError("RunPod Embed image는 latest tag를 사용해야 합니다.")
        if values["runpod_llm_image"] != "vllm/vllm-openai:latest":
            raise ValueError("RunPod vLLM image는 vllm/vllm-openai:latest여야 합니다.")
        resolve_model_preset(values["runpod_llm_model"])
        return cls(**{name: values[name] for name in required})


def load_secret_file(path: Path, *, required: bool = True) -> dict[str, str]:
    """Git 비추적 KEY=VALUE 파일을 shell 평가 없이 읽는다."""

    if not path.exists():
        if required:
            raise FileNotFoundError(f"secret 파일이 없습니다: {path}")
        return {}
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.replace("_", "").isalnum():
            raise ValueError(f"secret 파일 {line_number}행 형식이 잘못되었습니다.")
        values[key] = value.strip().strip("'\"")
    return values


def update_secret_file(path: Path, updates: Mapping[str, str]) -> None:
    """KEY 순서와 주석을 보존하며 secret 파일을 0600 권한으로 원자 갱신한다."""

    if not path.exists():
        raise FileNotFoundError(f"secret 파일이 없습니다: {path}")
    original_lines = path.read_text(encoding="utf-8").splitlines()
    matched: set[str] = set()
    updated_lines: list[str] = []
    for line in original_lines:
        key, separator, _ = line.partition("=")
        normalized_key = key.strip()
        if separator and normalized_key in updates:
            updated_lines.append(f"{normalized_key}={updates[normalized_key]}")
            matched.add(normalized_key)
        else:
            updated_lines.append(line)
    remaining = {
        key: value for key, value in updates.items() if key not in matched
    }
    if remaining:
        if updated_lines and updated_lines[-1]:
            updated_lines.append("")
        updated_lines.extend(f"{key}={value}" for key, value in remaining.items())

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write("\n".join(updated_lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
