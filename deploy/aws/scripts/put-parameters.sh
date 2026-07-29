#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: put-parameters.sh --file <non-secret JSON file> [--environment prod] [--dry-run]

JSON object의 key는 WorkShield 운영 Parameter Store allowlist여야 합니다.
비밀값은 이 script로 넣지 마세요. script는 parameter 이름만 출력합니다.
EOF
}

environment="prod"
input_file=""
dry_run=false
while (($#)); do
  case "$1" in
    --file) input_file="${2:-}"; shift 2 ;;
    --environment) environment="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ "$environment" =~ ^[a-z0-9-]+$ && -f "$input_file" ]] || { usage >&2; exit 2; }
mapfile -t entries < <(python3 - "$input_file" <<'PY'
import json
import re
import sys

allowed = {
    "release/active-sha", "vllm/base-url", "vllm/model",
    "runpod/llm/pod-id", "runpod/llm/base-url", "runpod/llm/model-id",
    "runpod/llm/template-id", "runpod/embed/pod-id", "runpod/embed/base-url",
    "runpod/embed/template-id", "runpod/last-provision-run-id",
    "api/session-ttl-seconds", "api/max-upload-size-bytes",
    "runtime/ghcr-owner", "runtime/nginx-image", "runtime/origin-domain",
}
values = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(values, dict) or set(values) - allowed:
    raise SystemExit("input contains an unsupported parameter name")
for name, value in values.items():
    if not isinstance(value, str) or not value or re.search(r"(?i)(secret|token|api[_-]?key|password)", name):
        raise SystemExit(f"invalid non-secret parameter: {name}")
    if "\n" in value or "\r" in value:
        raise SystemExit(f"multiline parameter is not allowed: {name}")
    print(f"{name}\t{value}")
PY
)

for entry in "${entries[@]}"; do
  name="${entry%%$'\t'*}"
  value="${entry#*$'\t'}"
  if [[ "$dry_run" == true ]]; then
    printf 'dry-run: parameter update: /workshield/%s/%s\n' "$environment" "$name"
  else
    aws ssm put-parameter --name "/workshield/${environment}/${name}" --value "$value" --type String --overwrite >/dev/null
    printf 'parameter updated: /workshield/%s/%s\n' "$environment" "$name"
  fi
done
