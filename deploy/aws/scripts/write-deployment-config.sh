#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: write-deployment-config.sh --output <path> --account-id <12 digits> --region <region> --availability-zone <az> --origin-domain <domain> --cloudfront-prefix-list-id <id> [--instance-type t3.small]

비밀이 아닌 GitHub Environment 변수 또는 관리자 입력에서 CDK 전용 config JSON을
생성합니다. 출력 파일에는 비밀을 넣지 마세요.
EOF
}

output=""
account_id=""
region=""
availability_zone=""
origin_domain=""
prefix_list_id=""
instance_type="t3.small"
while (($#)); do
  case "$1" in
    --output) output="${2:-}"; shift 2 ;;
    --account-id) account_id="${2:-}"; shift 2 ;;
    --region) region="${2:-}"; shift 2 ;;
    --availability-zone) availability_zone="${2:-}"; shift 2 ;;
    --origin-domain) origin_domain="${2:-}"; shift 2 ;;
    --cloudfront-prefix-list-id) prefix_list_id="${2:-}"; shift 2 ;;
    --instance-type) instance_type="${2:-}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ "$account_id" =~ ^[0-9]{12}$ && "$region" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ && "$availability_zone" =~ ^[a-z]{2}-[a-z]+-[0-9]+[a-z]$ ]] || { usage >&2; exit 2; }
[[ "$origin_domain" =~ ^[A-Za-z0-9.-]+$ && "$prefix_list_id" =~ ^pl-[0-9a-f]+$ && "$instance_type" =~ ^[a-z0-9.]+$ ]] || { usage >&2; exit 2; }
[[ -n "$output" ]] || { usage >&2; exit 2; }

python3 - "$output" "$account_id" "$region" "$availability_zone" "$origin_domain" "$prefix_list_id" "$instance_type" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
keys = (
    "aws_account_id", "aws_region", "availability_zone", "origin_domain",
    "cloudfront_origin_prefix_list_id", "instance_type",
)
values = dict(zip(keys, sys.argv[2:], strict=True))
values["app_name"] = "workshield-prod"
path.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
path.chmod(0o600)
PY
printf 'deployment config written: %s\n' "$output"
