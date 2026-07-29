#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: dispatch-ssm-command.sh --release-sha <40-character SHA> [--document-name workshield-prod-deploy] [--timeout-seconds 900] [--no-wait]

GitHub runner가 secret 없이 release SHA만 SSM Command document에 전달하고,
managed node의 안전한 성공 상태까지 기다립니다.
EOF
}

release_sha=""
document_name="workshield-prod-deploy"
timeout_seconds=900
wait_for_completion=true
while (($#)); do
  case "$1" in
    --release-sha) release_sha="${2:-}"; shift 2 ;;
    --document-name) document_name="${2:-}"; shift 2 ;;
    --timeout-seconds) timeout_seconds="${2:-}"; shift 2 ;;
    --no-wait) wait_for_completion=false; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ "$release_sha" =~ ^[0-9a-f]{40}$ && "$timeout_seconds" =~ ^[1-9][0-9]*$ ]] || { usage >&2; exit 2; }

command_id="$(aws ssm send-command \
  --document-name "$document_name" \
  --targets 'Key=tag:Project,Values=WorkShield' \
  --parameters "ReleaseSha=${release_sha}" \
  --comment "WorkShield release ${release_sha}" \
  --query 'Command.CommandId' --output text)"
printf 'SSM command submitted: %s\n' "$command_id"
[[ "$wait_for_completion" == true ]] || exit 0

deadline=$((SECONDS + timeout_seconds))
while (( SECONDS < deadline )); do
  status="$(aws ssm list-command-invocations --command-id "$command_id" --details --query 'CommandInvocations[0].Status' --output text 2>/dev/null || true)"
  case "$status" in
    Success) printf 'SSM command succeeded: %s\n' "$command_id"; exit 0 ;;
    Failed|Cancelled|TimedOut|Cancelling) printf 'error: SSM command status: %s\n' "$status" >&2; exit 1 ;;
    *) sleep 5 ;;
  esac
done
printf '%s\n' 'error: SSM command wait timed out.' >&2
exit 1
