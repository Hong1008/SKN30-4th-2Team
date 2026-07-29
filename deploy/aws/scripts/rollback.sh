#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: rollback.sh --release-sha <40-character SHA> [--dry-run]

이전 검증 release SHA를 deploy-containers.sh와 동일한 health·자동복구 절차로
적용합니다. DB schema와 사용자 data volume은 변경하지 않습니다.
EOF
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
exec "${script_dir}/deploy-containers.sh" "$@"
