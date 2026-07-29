#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: deploy-web.sh --release-sha <40-character SHA> --bucket <bucket> --distribution-id <id> [--web-dir web] [--dry-run]

검증된 web build를 versioned S3 bucket에 동기화하고 CloudFront 전체 경로를
invalidate합니다. release SHA는 object metadata로만 기록되며 secret은 취급하지 않습니다.
EOF
}

release_sha=""
bucket=""
distribution_id=""
web_dir="web"
dry_run=false
while (($#)); do
  case "$1" in
    --release-sha) release_sha="${2:-}"; shift 2 ;;
    --bucket) bucket="${2:-}"; shift 2 ;;
    --distribution-id) distribution_id="${2:-}"; shift 2 ;;
    --web-dir) web_dir="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ "$release_sha" =~ ^[0-9a-f]{40}$ && "$bucket" =~ ^[A-Za-z0-9.-]+$ && "$distribution_id" =~ ^[A-Z0-9]+$ && -d "$web_dir" ]] || { usage >&2; exit 2; }

if [[ "$dry_run" == true ]]; then
  printf 'dry-run: web release %s -> s3://%s, CloudFront %s\n' "$release_sha" "$bucket" "$distribution_id"
  exit 0
fi

(cd "$web_dir" && npm ci && npm run typecheck && npm test && npm run build)
aws s3 sync "${web_dir}/dist" "s3://${bucket}" --delete --only-show-errors --metadata "release-sha=${release_sha}"
invalidation_id="$(aws cloudfront create-invalidation --distribution-id "$distribution_id" --paths '/*' --query 'Invalidation.Id' --output text)"
aws cloudfront wait invalidation-completed --distribution-id "$distribution_id" --id "$invalidation_id"
printf 'web release activated: %s\n' "$release_sha"
