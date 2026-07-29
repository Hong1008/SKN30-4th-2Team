#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: rollback.sh --release-sha <40-character SHA> [--dry-run]

이전 검증 release SHA로 API·MCP container를 되돌리는 SSM 진입점입니다.
DB schema와 사용자 data volume은 이 명령으로 변경하지 않습니다.
EOF
}

release_sha=""
dry_run=false
while (($#)); do
  case "$1" in
    --release-sha)
      release_sha="${2:-}"
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
  printf '%s\n' 'error: --release-sha에는 40자리 소문자 Git SHA가 필요합니다.' >&2
  exit 2
fi

if [[ "$dry_run" == true ]]; then
  printf 'dry-run: release %s의 image 존재 여부와 rollback health check를 검증합니다.\n' "$release_sha"
  exit 0
fi

printf '%s\n' 'error: 실제 컨테이너 롤백은 6단계에서 구현됩니다. --dry-run을 사용하세요.' >&2
exit 1
