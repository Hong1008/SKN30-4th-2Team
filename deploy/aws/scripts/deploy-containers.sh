#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: deploy-containers.sh --release-sha <40-character SHA> [--dry-run]

SSM Run Command에서 API·MCP Compose release를 갱신하는 진입점입니다.
secret은 인수나 표준 출력으로 전달하지 않으며, 이후 단계에서 EC2 instance
role로 Secrets Manager를 읽어 root 전용 env 파일을 생성합니다.
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
  printf 'dry-run: release %s의 image manifest와 Compose health check를 검증합니다.\n' "$release_sha"
  exit 0
fi

printf '%s\n' 'error: 실제 컨테이너 배포는 6단계에서 구현됩니다. --dry-run을 사용하세요.' >&2
exit 1
