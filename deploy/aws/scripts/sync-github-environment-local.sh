#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: sync-github-environment-local.sh [--env-file <path>] [--environment <name>] [--repository <owner/repository>] [--dry-run]

로컬의 prod.env에서 허용된 비밀 아닌 값을 GitHub Environment Variables로 동기화합니다.
GitHub CLI 로그인은 필요 없으며, GH_TOKEN 또는 GITHUB_TOKEN 환경 변수에 repository
Environment를 관리할 수 있는 토큰을 설정해야 합니다. 토큰과 비밀값은 출력하지 않습니다.

허용 변수:
  AWS_ACCOUNT_ID AWS_REGION AWS_AVAILABILITY_ZONE AWS_DEPLOY_ROLE_ARN
  ORIGIN_DOMAIN
  CLOUDFRONT_ORIGIN_PREFIX_LIST_ID NGINX_IMAGE
EOF
}

env_file="deploy/aws/env/prod.env"
environment="production"
repository="Hong1008/SKN30-4th-2Team"
dry_run=false

while (($#)); do
  case "$1" in
    --env-file) env_file="${2:-}"; shift 2 ;;
    --environment) environment="${2:-}"; shift 2 ;;
    --repository) repository="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ -r "$env_file" && "$environment" =~ ^[A-Za-z0-9_.-]+$ && "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || {
  usage >&2
  exit 2
}

allowed=(
  AWS_ACCOUNT_ID AWS_REGION AWS_AVAILABILITY_ZONE AWS_DEPLOY_ROLE_ARN
  ORIGIN_DOMAIN
  CLOUDFRONT_ORIGIN_PREFIX_LIST_ID NGINX_IMAGE
)
declare -A values=()

while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  [[ -z "$line" || "$line" == \#* ]] && continue
  [[ "$line" == *=* ]] || { printf 'error: invalid env line in %s\n' "$env_file" >&2; exit 2; }
  key="${line%%=*}"
  value="${line#*=}"
  for allowed_key in "${allowed[@]}"; do
    if [[ "$key" == "$allowed_key" ]]; then
      values["$key"]="$value"
      break
    fi
  done
done < "$env_file"

for key in "${allowed[@]}"; do
  [[ -n "${values[$key]:-}" ]] || {
    printf 'error: %s must be set in %s\n' "$key" "$env_file" >&2
    exit 2
  }
done

if [[ "$dry_run" == true ]]; then
  printf 'dry-run: GitHub Environment %s in %s receives variables:\n' "$environment" "$repository"
  printf '  %s\n' "${allowed[@]}"
  exit 0
fi

token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
[[ -n "$token" ]] || {
  printf '%s\n' 'error: set GH_TOKEN (preferred) or GITHUB_TOKEN before running this script.' >&2
  exit 1
}
command -v curl >/dev/null || { printf '%s\n' 'error: curl is required.' >&2; exit 1; }

curl_config="$(mktemp)"
trap 'rm -f "$curl_config"' EXIT
printf 'header = "Accept: application/vnd.github+json"\n' > "$curl_config"
printf 'header = "X-GitHub-Api-Version: 2022-11-28"\n' >> "$curl_config"
printf 'header = "Authorization: Bearer %s"\n' "$token" >> "$curl_config"
unset token

api_base="https://api.github.com/repos/${repository}/environments/${environment}"
curl --fail --silent --show-error --config "$curl_config" --request PUT "$api_base" --output /dev/null

for key in "${allowed[@]}"; do
  body="$(python3 -c 'import json,sys; print(json.dumps({"name": sys.argv[1], "value": sys.argv[2]}))' "$key" "${values[$key]}")"
  variable_url="${api_base}/variables/${key}"
  variable_status="$(curl --silent --show-error --config "$curl_config" --output /dev/null --write-out '%{http_code}' "$variable_url")"
  case "$variable_status" in
    200)
      curl --fail --silent --show-error --config "$curl_config" \
        --request PATCH \
        --header 'Content-Type: application/json' \
        --data "$body" \
        "$variable_url" \
        --output /dev/null
      ;;
    404)
      curl --fail --silent --show-error --config "$curl_config" \
        --request POST \
        --header 'Content-Type: application/json' \
        --data "$body" \
        "${api_base}/variables" \
        --output /dev/null
      ;;
    *)
      printf 'error: GitHub could not read Environment variable %s (HTTP %s).\n' "$key" "$variable_status" >&2
      exit 1
      ;;
  esac
done

printf 'GitHub Environment variables synchronized: %s (%s)\n' "$repository" "$environment"
