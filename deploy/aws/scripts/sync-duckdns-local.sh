#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: sync-duckdns-local.sh [--profile <aws-profile>] [--region <aws-region>] [--domain <subdomain>] [--dry-run]

Foundation stack의 OriginElasticIp를 DuckDNS A 레코드로 동기화합니다.
DuckDNS 토큰은 AWS Secrets Manager의 /workshield/prod/duckdns에 DUCKDNS_TOKEN
키로만 보관하며, 명령 인자·로그·파일에 출력하지 않습니다.
EOF
}

profile="${AWS_PROFILE:-}"
region="${AWS_REGION:-ap-northeast-2}"
domain="workshield"
dry_run=false
while (($#)); do
  case "$1" in
    --profile) profile="${2:-}"; shift 2 ;;
    --region) region="${2:-}"; shift 2 ;;
    --domain) domain="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ -n "$profile" && "$region" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ && "$domain" =~ ^[a-z0-9-]+$ ]] || { usage >&2; exit 2; }
command -v aws >/dev/null && command -v curl >/dev/null && command -v python3 >/dev/null || { printf '%s\n' 'error: aws, curl, and python3 are required.' >&2; exit 1; }

aws_args=(--profile "$profile" --region "$region" --no-cli-pager)
ip_address="$(aws cloudformation describe-stacks "${aws_args[@]}" --stack-name WorkShieldFoundation --query 'Stacks[0].Outputs[?OutputKey==`OriginElasticIp`].OutputValue|[0]' --output text)"
[[ "$ip_address" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || { printf '%s\n' 'error: WorkShieldFoundation OriginElasticIp output is unavailable.' >&2; exit 1; }
if [[ "$dry_run" == true ]]; then
  printf 'dry-run: DuckDNS %s.duckdns.org A record will be updated to %s\n' "$domain" "$ip_address"
  exit 0
fi

token="$(aws secretsmanager get-secret-value "${aws_args[@]}" --secret-id /workshield/prod/duckdns --query SecretString --output text | python3 -c 'import json,sys; print(json.load(sys.stdin)["DUCKDNS_TOKEN"])')"
[[ -n "$token" ]] || { printf '%s\n' 'error: DUCKDNS_TOKEN is empty.' >&2; exit 1; }
curl_config="$(mktemp)"
trap 'rm -f "$curl_config"' EXIT
python3 - "$curl_config" "$domain" "$token" "$ip_address" <<'PY'
import sys
from pathlib import Path
from urllib.parse import urlencode

path, domain, token, ip_address = map(str, sys.argv[1:])
query = urlencode({"domains": domain, "token": token, "ip": ip_address, "verbose": "true"})
Path(path).write_text(f'url = "https://www.duckdns.org/update?{query}"\n', encoding="utf-8")
Path(path).chmod(0o600)
PY
response="$(curl --fail --silent --show-error --config "$curl_config")"
[[ "$response" == OK* ]] || { printf '%s\n' 'error: DuckDNS update was not accepted.' >&2; exit 1; }
printf 'DuckDNS A record updated: %s.duckdns.org -> %s\n' "$domain" "$ip_address"
