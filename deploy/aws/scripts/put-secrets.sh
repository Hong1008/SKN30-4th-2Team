#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: put-secrets.sh --secret <vllm|embed|origin-header|law|duckdns> [--environment prod] [--stdin|--generate] [--dry-run]

비밀값을 command argument로 받지 않습니다. 기본값은 숨김 대화형 입력이며,
--stdin은 안전한 stdin pipe, --generate는 vllm/embed/origin-header의 새 32-byte key만
생성합니다. 이 명령은 비밀값을 출력하지 않습니다.
EOF
}

environment="prod"
secret_name=""
input_mode="interactive"
dry_run=false
while (($#)); do
  case "$1" in
    --secret) secret_name="${2:-}"; shift 2 ;;
    --environment) environment="${2:-}"; shift 2 ;;
    --stdin) input_mode="stdin"; shift ;;
    --generate) input_mode="generate"; shift ;;
    --dry-run) dry_run=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ "$environment" =~ ^[a-z0-9-]+$ ]] || { printf '%s\n' 'error: invalid environment.' >&2; exit 2; }
case "$secret_name" in
  vllm) key="VLLM_API_KEY" ;;
  embed) key="RUNPOD_EMBED_API_KEY" ;;
  origin-header) key="ORIGIN_HEADER" ;;
  law) key="LAW_OC" ;;
  duckdns) key="DUCKDNS_TOKEN" ;;
  *) usage >&2; exit 2 ;;
esac
if [[ "$input_mode" == "generate" && ( "$secret_name" == "law" || "$secret_name" == "duckdns" ) ]]; then
  printf '%s\n' 'error: LAW_OC와 DUCKDNS_TOKEN은 사용자가 발급한 값을 입력해야 합니다.' >&2
  exit 2
fi

if [[ "$dry_run" == true ]]; then
  printf 'dry-run: /workshield/%s/%s secret의 %s key를 갱신합니다.\n' "$environment" "$secret_name" "$key"
  exit 0
fi

case "$input_mode" in
  interactive)
    read -r -s -p "${key}: " value < /dev/tty
    printf '\n' > /dev/tty
    ;;
  stdin) IFS= read -r value ;;
  generate) value="$(openssl rand -hex 32)" ;;
esac
[[ -n "${value:-}" ]] || { printf '%s\n' 'error: empty secret is not allowed.' >&2; exit 2; }

temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT
secret_file="${temp_dir}/secret.json"
printf '%s' "$value" | python3 -c 'import json,sys; print(json.dumps({sys.argv[1]: sys.stdin.read()}))' "$key" > "$secret_file"
secret_id="/workshield/${environment}/${secret_name}"

if aws secretsmanager describe-secret --secret-id "$secret_id" >/dev/null 2>&1; then
  aws secretsmanager put-secret-value --secret-id "$secret_id" --secret-string "file://${secret_file}" >/dev/null
else
  aws secretsmanager create-secret --name "$secret_id" --secret-string "file://${secret_file}" >/dev/null
fi
printf 'secret updated: %s\n' "$secret_id"
