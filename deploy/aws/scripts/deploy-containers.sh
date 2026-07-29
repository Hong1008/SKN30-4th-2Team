#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly ENVIRONMENT="prod"
readonly PARAMETER_PREFIX="/workshield/${ENVIRONMENT}"
readonly RUNTIME_DIR="/opt/workshield/runtime"
readonly RELEASE_DIR="/opt/workshield/releases"
readonly SECRET_DIR="/opt/workshield/secrets"

usage() {
  cat <<'EOF'
Usage: deploy-containers.sh --release-sha <40-character SHA> [--dry-run]

SSM Run Command가 실행하는 EC2 전용 container release entrypoint입니다.
Secrets Manager에서 비밀을 직접 읽어 root 전용 env file을 만들고, Compose health
검증에 성공한 release만 활성 SHA로 기록합니다. secret 값은 인수·로그에 출력하지 않습니다.
EOF
}

release_sha=""
dry_run=false
while (($#)); do
  case "$1" in
    --release-sha) release_sha="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
  printf '%s\n' 'error: --release-sha에는 40자리 소문자 Git SHA가 필요합니다.' >&2
  exit 2
fi

require_parameter() {
  local name="$1" value
  value="$(aws ssm get-parameter --name "${PARAMETER_PREFIX}/${name}" --query 'Parameter.Value' --output text)"
  if [[ -z "$value" || "$value" == "__UNSET__" ]]; then
    printf 'error: required runtime parameter is not configured: %s\n' "$name" >&2
    return 1
  fi
  printf '%s' "$value"
}

secret_to_file() {
  local secret_id="$1" target="$2"
  aws secretsmanager get-secret-value --secret-id "$secret_id" --query SecretString --output text > "$target"
}

validate_runtime_values() {
  [[ "$1" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || return 1
  [[ "$2" =~ ^nginx@sha256:[0-9a-f]{64}$ ]] || return 1
  [[ "$3" =~ ^[A-Za-z0-9.-]+$ ]] || return 1
}

stage_paths=()
staged_path=""
secret_temp="$(mktemp -d)"
cleanup() {
  rm -rf "$secret_temp"
  for stage in "${stage_paths[@]}"; do
    [[ -n "$stage" ]] && rm -rf "$stage"
  done
}
trap cleanup EXIT

if [[ "$dry_run" == true ]]; then
  printf 'dry-run: release %s의 secret identifier, Compose interpolation, health, rollback을 검증합니다.\n' "$release_sha"
  exit 0
fi

test -f "${RUNTIME_DIR}/compose.prod.yaml"
test -f "${RUNTIME_DIR}/nginx/nginx.conf.template"

vllm_base_url="$(require_parameter 'vllm/base-url')"
vllm_model="$(require_parameter 'vllm/model')"
embed_base_url="$(require_parameter 'runpod/embed/base-url')"
ghcr_owner="$(require_parameter 'runtime/ghcr-owner')"
nginx_image="$(require_parameter 'runtime/nginx-image')"
origin_domain="$(require_parameter 'runtime/origin-domain')"
validate_runtime_values "$ghcr_owner" "$nginx_image" "$origin_domain" || {
  printf '%s\n' 'error: runtime parameter format is invalid.' >&2
  exit 1
}

secret_to_file "${PARAMETER_PREFIX}/vllm" "${secret_temp}/vllm.json"
secret_to_file "${PARAMETER_PREFIX}/embed" "${secret_temp}/embed.json"
secret_to_file "${PARAMETER_PREFIX}/origin-header" "${secret_temp}/origin.json"
secret_to_file "${PARAMETER_PREFIX}/law" "${secret_temp}/law.json"

stage_release() {
  local target_sha="$1" stage
  stage="$(mktemp -d "${RELEASE_DIR}/.stage.XXXXXX")"
  stage_paths+=("$stage")
  install -d -m 0755 "$stage/nginx" "$SECRET_DIR"
  cp "$RUNTIME_DIR/compose.prod.yaml" "$stage/compose.prod.yaml"
  cp "$RUNTIME_DIR/nginx/nginx.conf.template" "$stage/nginx/nginx.conf.template"
  python3 - "$stage/api.env" "$stage/mcp.env" "$stage/runtime.env" \
    "${secret_temp}/vllm.json" "${secret_temp}/embed.json" "${secret_temp}/origin.json" "${secret_temp}/law.json" \
    "$vllm_base_url" "$vllm_model" "$embed_base_url" "$ghcr_owner" "$nginx_image" "$origin_domain" "$target_sha" <<'PY'
import json
import sys
from pathlib import Path

api_path, mcp_path, runtime_path = map(Path, sys.argv[1:4])
vllm_path, embed_path, origin_path, law_path = map(Path, sys.argv[4:8])
vllm_url, model_id, embed_url, owner, nginx_image, origin_domain, release_sha = sys.argv[8:]

def value(path: Path, key: str) -> str:
    raw = json.loads(path.read_text(encoding="utf-8"))
    item = raw.get(key)
    if not isinstance(item, str) or not item:
        raise SystemExit(f"missing required secret key: {key}")
    return item

def write(path: Path, values: dict[str, str]) -> None:
    path.write_text("".join(f"{key}={json.dumps(item)}\n" for key, item in values.items()), encoding="utf-8")
    path.chmod(0o600)

write(api_path, {
    "VLLM_API_KEY": value(vllm_path, "VLLM_API_KEY"),
    "VLLM_BASE_URL": vllm_url,
    "LLM_MODEL": model_id,
})
write(mcp_path, {
    "LAW_OC": value(law_path, "LAW_OC"),
    "RUNPOD_POD_BASE_URL": embed_url,
    "RUNPOD_EMBED_API_KEY": value(embed_path, "RUNPOD_EMBED_API_KEY"),
})
write(runtime_path, {
    "GHCR_OWNER": owner,
    "RELEASE_SHA": release_sha,
    "NGINX_IMAGE": nginx_image,
    "ORIGIN_DOMAIN": origin_domain,
    "ORIGIN_HEADER": value(origin_path, "ORIGIN_HEADER"),
    "WORKSHIELD_DATA_DIR": "/opt/workshield/data",
    "API_ENV_FILE": str(api_path),
    "MCP_ENV_FILE": str(mcp_path),
})
PY
  staged_path="$stage"
}

wait_for_api() {
  local stage="$1" attempt
  for attempt in $(seq 1 30); do
    if docker compose --project-name workshield-prod --env-file "$stage/runtime.env" -f "$stage/compose.prod.yaml" \
      exec -T api python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health/ready', timeout=5).read()" >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}

activate_release() {
  local target_sha="$1" stage
  stage_release "$target_sha"
  stage="$staged_path"
  docker compose --project-name workshield-prod --env-file "$stage/runtime.env" -f "$stage/compose.prod.yaml" config --quiet
  docker compose --project-name workshield-prod --env-file "$stage/runtime.env" -f "$stage/compose.prod.yaml" pull --quiet
  docker compose --project-name workshield-prod --env-file "$stage/runtime.env" -f "$stage/compose.prod.yaml" up -d --remove-orphans
  for service in api mcp nginx; do
    docker compose --project-name workshield-prod --env-file "$stage/runtime.env" -f "$stage/compose.prod.yaml" \
      ps --status running --services | grep -qx "$service"
  done
  wait_for_api "$stage"
  install -m 0600 "$stage/api.env" "${SECRET_DIR}/api.env"
  install -m 0600 "$stage/mcp.env" "${SECRET_DIR}/mcp.env"
  install -m 0600 "$stage/runtime.env" "${SECRET_DIR}/runtime.env"
}

previous_sha="$(aws ssm get-parameter --name "${PARAMETER_PREFIX}/release/active-sha" --query 'Parameter.Value' --output text 2>/dev/null || true)"
if activate_release "$release_sha"; then
  aws ssm put-parameter --name "${PARAMETER_PREFIX}/release/active-sha" --value "$release_sha" --type String --overwrite >/dev/null
  printf 'release activated: %s\n' "$release_sha"
  exit 0
fi

printf '%s\n' 'error: release health check failed; attempting previous verified release.' >&2
if [[ "$previous_sha" =~ ^[0-9a-f]{40}$ && "$previous_sha" != "$release_sha" ]] && activate_release "$previous_sha"; then
  printf 'previous release restored: %s\n' "$previous_sha" >&2
else
  printf '%s\n' 'error: automatic rollback could not restore a healthy release.' >&2
fi
exit 1
