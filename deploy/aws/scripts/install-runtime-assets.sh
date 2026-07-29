#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install-runtime-assets.sh [--timeout-seconds 300] [--dry-run]

GitHub runner 또는 관리자 terminal에서 WorkShield SSM managed node에 secret 없는
container deployment script와 Compose/Nginx template을 설치합니다. 자산은 SSM
Command parameter file로 전달되며 secret을 포함하지 않습니다.
EOF
}

timeout_seconds=300
dry_run=false
while (($#)); do
  case "$1" in
    --timeout-seconds) timeout_seconds="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]] || { usage >&2; exit 2; }

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
declare -a sources=(
  "${root}/deploy/aws/scripts/deploy-containers.sh:/opt/workshield/deploy-containers.sh:0700"
  "${root}/deploy/aws/scripts/rollback.sh:/opt/workshield/rollback.sh:0700"
  "${root}/deploy/aws/compose.prod.yaml:/opt/workshield/runtime/compose.prod.yaml:0644"
  "${root}/deploy/aws/nginx/nginx.conf.template:/opt/workshield/runtime/nginx/nginx.conf.template:0644"
)

if [[ "$dry_run" == true ]]; then
  for source in "${sources[@]}"; do printf 'dry-run: install %s\n' "${source#*:}"; done
  exit 0
fi

payload="$(mktemp)"
trap 'rm -f "$payload"' EXIT
python3 - "$payload" "${sources[@]}" <<'PY'
import base64
import json
import sys
from pathlib import Path

commands = ["set -euo pipefail", "install -d -m 0755 /opt/workshield/runtime/nginx /opt/workshield/releases /opt/workshield/secrets"]
for item in sys.argv[2:]:
    source, destination, mode = item.rsplit(":", 2)
    encoded = base64.b64encode(Path(source).read_bytes()).decode("ascii")
    encoded_path = f"{destination}.b64"
    commands.append(f": > {encoded_path}")
    for offset in range(0, len(encoded), 3000):
        commands.append(f"printf '%s' '{encoded[offset:offset + 3000]}' >> {encoded_path}")
    commands.extend([
        f"base64 -d {encoded_path} > {destination}",
        f"rm -f {encoded_path}",
        f"chmod {mode} {destination}",
    ])
json.dump({"commands": commands}, open(sys.argv[1], "w", encoding="utf-8"))
PY

command_id="$(aws ssm send-command \
  --document-name AWS-RunShellScript \
  --targets 'Key=tag:Project,Values=WorkShield' \
  --parameters "file://${payload}" \
  --comment 'Install WorkShield runtime assets' \
  --query 'Command.CommandId' --output text)"
printf 'runtime asset command submitted: %s\n' "$command_id"

deadline=$((SECONDS + timeout_seconds))
while (( SECONDS < deadline )); do
  status="$(aws ssm list-command-invocations --command-id "$command_id" --details --query 'CommandInvocations[0].Status' --output text 2>/dev/null || true)"
  case "$status" in
    Success) printf 'runtime assets installed: %s\n' "$command_id"; exit 0 ;;
    Failed|Cancelled|TimedOut|Cancelling) printf 'error: runtime asset command status: %s\n' "$status" >&2; exit 1 ;;
    *) sleep 5 ;;
  esac
done
printf '%s\n' 'error: runtime asset installation timed out.' >&2
exit 1
