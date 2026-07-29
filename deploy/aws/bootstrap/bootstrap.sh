#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bootstrap.sh [--profile <aws-profile>] [--region <aws-region>] [--account-id <12 digits>] [--dry-run]

GitHub OIDC provider, production deploy role, CloudFormation execution role와
CDK bootstrap을 준비하는 관리자용 진입점입니다.

기본 repository와 Environment는 Hong1008/SKN30-4th-2Team의 production,
production-destroy입니다. --dry-run은 AWS를 변경하지 않습니다.
EOF
}

profile="${AWS_PROFILE:-}"
region="${AWS_REGION:-ap-northeast-2}"
account_id=""
dry_run=false

while (($#)); do
  case "$1" in
    --profile) profile="${2:-}"; shift 2 ;;
    --region) region="${2:-}"; shift 2 ;;
    --account-id) account_id="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ -n "$profile" && "$region" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ ]] || { usage >&2; exit 2; }
command -v aws >/dev/null || { printf '%s\n' 'error: AWS CLI v2 is required.' >&2; exit 1; }

aws_args=(--profile "$profile" --region "$region" --no-cli-pager)
caller_account="$(aws sts get-caller-identity "${aws_args[@]}" --query Account --output text)"
if [[ -n "$account_id" && "$account_id" != "$caller_account" ]]; then
  printf '%s\n' 'error: --account-id does not match the authenticated AWS account.' >&2
  exit 2
fi
account_id="$caller_account"

template_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "$template_dir/../../.." && pwd)"
template="$template_dir/github-oidc-role.yaml"
policy_arn="arn:aws:iam::${account_id}:policy/workshield-prod-infrastructure"

if [[ "$dry_run" == true ]]; then
  printf 'dry-run: account=%s region=%s profile=%s\n' "$account_id" "$region" "$profile"
  printf '%s\n' 'dry-run: deploy CloudFormation stack workshield-prod-github-oidc (OIDC provider and IAM roles).'
  printf 'dry-run: run CDK bootstrap with execution policy %s.\n' "$policy_arn"
  exit 0
fi

aws cloudformation deploy "${aws_args[@]}" \
  --stack-name workshield-prod-github-oidc \
  --template-file "$template" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    GitHubOrganization=Hong1008 \
    GitHubRepository=SKN30-4th-2Team \
    GitHubEnvironment=production \
    GitHubDestructionEnvironment=production-destroy \
    DeployRoleName=workshield-prod-github-deploy \
    BootstrapQualifier=hnb659fds

command -v npm >/dev/null || { printf '%s\n' 'error: npm is required for the pinned CDK CLI.' >&2; exit 1; }
command -v uv >/dev/null || { printf '%s\n' 'error: uv is required for the CDK Python app.' >&2; exit 1; }
(
  cd "$repository_root/deploy/aws/iac"
  uv sync --frozen --no-dev
  npm ci
  # CDK CLI가 role chain profile을 해석하지 못하는 환경에서도 AWS CLI가
  # 발급한 단기 자격증명만 이 서브셸에 전달한다. 어떤 값도 출력하거나 저장하지 않는다.
  eval "$(aws configure export-credentials --profile "$profile" --format env)"
  AWS_REGION="$region" AWS_SDK_LOAD_CONFIG=1 npm exec cdk -- bootstrap "aws://${account_id}/${region}" \
    --trust "$account_id" \
    --cloudformation-execution-policies "$policy_arn"
)

deploy_role_arn="$(aws cloudformation describe-stacks "${aws_args[@]}" --stack-name workshield-prod-github-oidc --query \"Stacks[0].Outputs[?OutputKey=='GitHubDeployRoleArn'].OutputValue\" --output text)"
printf 'bootstrap complete: GitHub deploy role ARN=%s\n' "$deploy_role_arn"
