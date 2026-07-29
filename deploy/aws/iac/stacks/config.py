"""비밀이 아닌 배포 대상 설정을 읽고 검증한다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DeploymentConfig:
    """CDK synth에 필요한 공개 배포 식별자."""

    app_name: str
    aws_account_id: str
    aws_region: str
    availability_zone: str
    origin_domain: str
    cloudfront_origin_prefix_list_id: str
    instance_type: str

    @classmethod
    def from_file(cls, path: Path) -> "DeploymentConfig":
        """JSON 설정 파일을 읽어 누락된 필수 식별자를 빠르게 실패시킨다."""
        values = json.loads(path.read_text(encoding="utf-8"))
        required = {
            "app_name",
            "aws_account_id",
            "aws_region",
            "availability_zone",
            "origin_domain",
            "cloudfront_origin_prefix_list_id",
            "instance_type",
        }
        missing = sorted(required - values.keys())
        if missing:
            raise ValueError(f"배포 설정에 필수 값이 없습니다: {', '.join(missing)}")
        if not values["aws_account_id"].isdigit() or len(values["aws_account_id"]) != 12:
            raise ValueError("aws_account_id는 12자리 숫자여야 합니다.")
        if not values["cloudfront_origin_prefix_list_id"].startswith("pl-"):
            raise ValueError("cloudfront_origin_prefix_list_id는 pl-로 시작해야 합니다.")
        return cls(**{name: values[name] for name in required})
