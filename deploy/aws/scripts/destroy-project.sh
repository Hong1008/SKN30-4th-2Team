#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: destroy-project.sh --confirmation 'DESTROY workshield-prod' [--environment prod] [--dry-run]

WorkShield 소유 RunPod Pod·CloudFormation stack·남은 Parameter Store 항목만
삭제하고, secret은 7일 복구 기간으로 삭제 예약합니다. hosted zone, domain,
OIDC provider, CDK bootstrap, RunPod template, GHCR package는 보존합니다.
EOF
}

confirmation=""
environment="prod"
dry_run=false
while (($#)); do
  case "$1" in
    --confirmation) confirmation="${2:-}"; shift 2 ;;
    --environment) environment="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ "$confirmation" == "DESTROY workshield-prod" && "$environment" == "prod" ]] || { usage >&2; exit 2; }

if [[ "$dry_run" == true ]]; then
  printf '%s\n' 'dry-run: RunPod state, WorkShield stacks, project parameters, 7-day secret deletion을 확인합니다.'
  exit 0
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
python3 "${repo_root}/mcp/deploy/rm_embed_pod.py" --state-backend aws --environment "$environment" --ignore-not-found
python3 "${repo_root}/deploy/llm_pod/rm_llm_pod.py" --state-backend aws --environment "$environment" --ignore-not-found

for stack in WorkShieldService WorkShieldFoundation; do
  if aws cloudformation describe-stacks --stack-name "$stack" >/dev/null 2>&1; then
    aws cloudformation delete-stack --stack-name "$stack"
    aws cloudformation wait stack-delete-complete --stack-name "$stack"
    printf 'stack deleted: %s\n' "$stack"
  fi
done

while :; do
  names="$(aws ssm get-parameters-by-path --path "/workshield/${environment}" --recursive --query 'Parameters[].Name' --output text 2>/dev/null || true)"
  [[ -z "$names" || "$names" == "None" ]] && break
  read -r -a batch <<< "$names"
  aws ssm delete-parameters --names "${batch[@]}" >/dev/null
done

for secret_id in "/workshield/${environment}/vllm" "/workshield/${environment}/embed" "/workshield/${environment}/origin-header" "/workshield/${environment}/law"; do
  if aws secretsmanager describe-secret --secret-id "$secret_id" >/dev/null 2>&1; then
    aws secretsmanager delete-secret --secret-id "$secret_id" --recovery-window-in-days 7 >/dev/null || true
    printf 'secret deletion scheduled: %s\n' "$secret_id"
  fi
done

remaining_stacks=()
for stack in WorkShieldService WorkShieldFoundation; do
  if aws cloudformation describe-stacks --stack-name "$stack" >/dev/null 2>&1; then
    remaining_stacks+=("$stack")
  fi
done
remaining_parameters="$(aws ssm get-parameters-by-path --path "/workshield/${environment}" --recursive --query 'Parameters[].Name' --output text 2>/dev/null || true)"
if ((${#remaining_stacks[@]})); then
  printf 'remaining WorkShield stacks: %s\n' "${remaining_stacks[*]}" >&2
else
  printf '%s\n' 'remaining WorkShield stacks: none'
fi
if [[ -n "$remaining_parameters" && "$remaining_parameters" != "None" ]]; then
  printf 'remaining WorkShield parameters: %s\n' "$remaining_parameters" >&2
else
  printf '%s\n' 'remaining WorkShield parameters: none'
fi
printf '%s\n' 'scheduled secret remnants: /workshield/prod/{vllm,embed,origin-header,law} (7-day recovery window).'
printf '%s\n' 'retained shared resources: hosted zone, domain registration, GitHub OIDC provider, CDK bootstrap, RunPod templates, GHCR packages.'
