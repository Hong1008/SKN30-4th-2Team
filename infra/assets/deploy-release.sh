#!/usr/bin/env bash
# EC2에서만 실행되는 WorkShield release 적용기다.
set -euo pipefail
umask 077

readonly ENVIRONMENT="prod"
readonly PARAMETER_PREFIX="/workshield/${ENVIRONMENT}"
readonly RUNTIME_DIR="/opt/workshield/runtime"
readonly RELEASE_DIR="/opt/workshield/releases"
readonly SECRET_DIR="/opt/workshield/secrets"

usage() {
  cat <<'EOF'
Usage: deploy-release.sh --release-tag <tag> --api-image <digest-ref> --mcp-image <digest-ref> [--dry-run]

SSM Run Command가 실행하는 EC2 전용 container release entrypoint입니다.
Secrets Manager에서 비밀을 직접 읽어 root 전용 env file을 만들고, Compose health
검증에 성공한 release tag와 image digest만 기록합니다. secret 값은 출력하지 않습니다.
EOF
}

release_tag=""
api_image=""
mcp_image=""
dry_run=false
while (($#)); do
  case "$1" in
    --release-tag) release_tag="${2:-}"; shift 2 ;;
    --api-image) api_image="${2:-}"; shift 2 ;;
    --mcp-image) mcp_image="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

if [[ ! "$release_tag" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] \
  || [[ ! "$api_image" =~ ^ghcr\.io/.+@sha256:[0-9a-f]{64}$ ]] \
  || [[ ! "$mcp_image" =~ ^ghcr\.io/.+@sha256:[0-9a-f]{64}$ ]]; then
  printf '%s\n' 'error: 유효한 release tag와 API/MCP digest reference가 필요합니다.' >&2
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
  printf 'dry-run: release %s의 Compose interpolation, health, rollback을 검증합니다.\n' "$release_tag"
  exit 0
fi

test -f "${RUNTIME_DIR}/compose.prod.yaml"
test -f "${RUNTIME_DIR}/nginx/nginx.conf.template"

binding="$(require_parameter 'runtime/binding')"
readarray -t binding_values < <(
  printf '%s' "$binding" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["vllm_base_url"]); print(d["vllm_model"]); print(d["embed_base_url"]); print(d["nginx_image"]); print(d["origin_domain"])'
)
vllm_base_url="${binding_values[0]}"
vllm_model="${binding_values[1]}"
embed_base_url="${binding_values[2]}"
nginx_image="${binding_values[3]}"
origin_domain="${binding_values[4]}"
validate_runtime_values "workshield" "$nginx_image" "$origin_domain" || {
  printf '%s\n' 'error: runtime parameter format is invalid.' >&2
  exit 1
}

secret_to_file "${PARAMETER_PREFIX}/vllm" "${secret_temp}/vllm.json"
secret_to_file "${PARAMETER_PREFIX}/embed" "${secret_temp}/embed.json"
secret_to_file "${PARAMETER_PREFIX}/origin-header" "${secret_temp}/origin.json"
secret_to_file "${PARAMETER_PREFIX}/law" "${secret_temp}/law.json"

stage_release() {
  local target_tag="$1" target_api_image="$2" target_mcp_image="$3" stage
  stage="$(mktemp -d "${RELEASE_DIR}/.stage.XXXXXX")"
  stage_paths+=("$stage")
  install -d -m 0755 "$stage/nginx" "$SECRET_DIR"
  cp "$RUNTIME_DIR/compose.prod.yaml" "$stage/compose.prod.yaml"
  cp "$RUNTIME_DIR/nginx/nginx.conf.template" "$stage/nginx/nginx.conf.template"
  python3 - "$stage/api.env" "$stage/mcp.env" "$stage/runtime.env" \
    "${secret_temp}/vllm.json" "${secret_temp}/embed.json" "${secret_temp}/origin.json" "${secret_temp}/law.json" \
    "$vllm_base_url" "$vllm_model" "$embed_base_url" "$nginx_image" "$origin_domain" \
    "$target_tag" "$target_api_image" "$target_mcp_image" <<'PY'
import json
import sys
from pathlib import Path

api_path, mcp_path, runtime_path = map(Path, sys.argv[1:4])
vllm_path, embed_path, origin_path, law_path = map(Path, sys.argv[4:8])
vllm_url, model_id, embed_url, nginx_image, origin_domain, release_tag, api_image, mcp_image = sys.argv[8:]

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
    "RELEASE_TAG": release_tag,
    "API_IMAGE": api_image,
    "MCP_IMAGE": mcp_image,
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

wait_for_compose_health() {
  local stage="$1" service="$2" attempt container_id status
  for attempt in $(seq 1 40); do
    container_id="$(docker compose --project-name workshield-prod --env-file "$stage/runtime.env" -f "$stage/compose.prod.yaml" ps -q "$service")"
    status="$(docker inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)"
    [[ "$status" == "healthy" ]] && return 0
    [[ "$status" == "unhealthy" ]] && return 1
    sleep 5
  done
  return 1
}

activate_release() {
  local target_tag="$1" target_api_image="$2" target_mcp_image="$3" stage final
  stage_release "$target_tag" "$target_api_image" "$target_mcp_image" || return
  stage="$staged_path"
  docker compose --project-name workshield-prod --env-file "$stage/runtime.env" -f "$stage/compose.prod.yaml" config --quiet || return
  docker compose --project-name workshield-prod --env-file "$stage/runtime.env" -f "$stage/compose.prod.yaml" pull --quiet || return
  docker compose --project-name workshield-prod --env-file "$stage/runtime.env" -f "$stage/compose.prod.yaml" up -d --remove-orphans || return
  for service in api mcp nginx; do
    docker compose --project-name workshield-prod --env-file "$stage/runtime.env" -f "$stage/compose.prod.yaml" \
      ps --status running --services | grep -qx "$service" || return
  done
  wait_for_compose_health "$stage" mcp || return
  wait_for_compose_health "$stage" api || return
  wait_for_api "$stage" || return
  final="${RELEASE_DIR}/${target_tag}-$(date +%s)-$$"
  mv "$stage" "$final" || return
  install -m 0600 "$final/api.env" "${SECRET_DIR}/api.env" || return
  install -m 0600 "$final/mcp.env" "${SECRET_DIR}/mcp.env" || return
  install -m 0600 "$final/runtime.env" "${SECRET_DIR}/runtime.env" || return
  ln -s "$final" "${RELEASE_DIR}/.current.$$" || return
  mv -Tf "${RELEASE_DIR}/.current.$$" "${RELEASE_DIR}/current" || return
}

previous_tag="$(aws ssm get-parameter --name "${PARAMETER_PREFIX}/release/active-tag" --query 'Parameter.Value' --output text 2>/dev/null || true)"
previous_api_image="$(aws ssm get-parameter --name "${PARAMETER_PREFIX}/release/active-api-image" --query 'Parameter.Value' --output text 2>/dev/null || true)"
previous_mcp_image="$(aws ssm get-parameter --name "${PARAMETER_PREFIX}/release/active-mcp-image" --query 'Parameter.Value' --output text 2>/dev/null || true)"
if activate_release "$release_tag" "$api_image" "$mcp_image"; then
  aws ssm put-parameter --name "${PARAMETER_PREFIX}/release/active-tag" --value "$release_tag" --type String --overwrite >/dev/null
  aws ssm put-parameter --name "${PARAMETER_PREFIX}/release/active-api-image" --value "$api_image" --type String --overwrite >/dev/null
  aws ssm put-parameter --name "${PARAMETER_PREFIX}/release/active-mcp-image" --value "$mcp_image" --type String --overwrite >/dev/null
  printf 'release activated: %s\n' "$release_tag"
  exit 0
fi

printf '%s\n' 'error: release health check failed; attempting previous verified release.' >&2
if [[ "$previous_tag" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] \
  && [[ "$previous_api_image" =~ @sha256:[0-9a-f]{64}$ ]] \
  && [[ "$previous_mcp_image" =~ @sha256:[0-9a-f]{64}$ ]] \
  && activate_release "$previous_tag" "$previous_api_image" "$previous_mcp_image"; then
  printf 'previous release restored: %s\n' "$previous_tag" >&2
else
  printf '%s\n' 'error: automatic rollback could not restore a healthy release.' >&2
fi
exit 1
