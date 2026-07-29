#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bootstrap.sh [--dry-run]

GitHub OIDC provider, production deploy role, CloudFormation execution role와
CDK bootstrap을 준비하는 관리자용 진입점입니다.

현재는 구현 골격 단계이므로 AWS를 변경하지 않습니다. --dry-run은 예정된
작업만 출력합니다.
EOF
}

case "${1:---help}" in
  --help|-h)
    usage
    ;;
  --dry-run)
    printf '%s\n' 'dry-run: GitHub OIDC role 및 CDK bootstrap 변경은 수행하지 않습니다.'
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
