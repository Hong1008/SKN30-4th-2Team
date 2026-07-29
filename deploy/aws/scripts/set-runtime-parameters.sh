#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: set-runtime-parameters.sh --ghcr-owner <owner> --nginx-image <nginx@sha256:digest> --origin-domain <domain> [--environment prod] [--dry-run]

컨테이너 release에 필요한 비밀이 아닌 runtime Parameter Store 값을 갱신합니다.
EOF
}

environment="prod"
ghcr_owner=""
nginx_image=""
origin_domain=""
dry_run=false
while (($#)); do
  case "$1" in
    --environment) environment="${2:-}"; shift 2 ;;
    --ghcr-owner) ghcr_owner="${2:-}"; shift 2 ;;
    --nginx-image) nginx_image="${2:-}"; shift 2 ;;
    --origin-domain) origin_domain="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ "$environment" =~ ^[a-z0-9-]+$ && "$ghcr_owner" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || { usage >&2; exit 2; }
[[ "$nginx_image" =~ ^nginx@sha256:[0-9a-f]{64}$ && "$origin_domain" =~ ^[A-Za-z0-9.-]+$ ]] || { usage >&2; exit 2; }

temporary_file="$(mktemp)"
trap 'rm -f "$temporary_file"' EXIT
python3 - "$temporary_file" "$ghcr_owner" "$nginx_image" "$origin_domain" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(json.dumps({
    "runtime/ghcr-owner": sys.argv[2],
    "runtime/nginx-image": sys.argv[3],
    "runtime/origin-domain": sys.argv[4],
}), encoding="utf-8")
PY

args=(--file "$temporary_file" --environment "$environment")
[[ "$dry_run" == true ]] && args+=(--dry-run)
"$(dirname "${BASH_SOURCE[0]}")/put-parameters.sh" "${args[@]}"
