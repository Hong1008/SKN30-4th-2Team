set shell := ["bash", "-euo", "pipefail", "-c"]

task := "env PYTHONPATH=infra/src uv run --project infra python -m workshield_infra.tasks"

default:
    @just --list

# 내부 Python/CDK 의존성을 lockfile 그대로 설치한다.
infra-init:
    git submodule update --init --recursive
    uv sync --project infra --frozen
    npm ci --prefix infra

# 로컬 도구, 설정, secret 권한, submodule 경계를 검사한다.
infra-check environment="prod":
    {{task}} check --environment "{{environment}}"

# CDK bootstrap과 application deploy 권한이 없는 GitHub OIDC role을 준비한다.
infra-bootstrap profile environment="prod":
    {{task}} bootstrap --profile "{{profile}}" --environment "{{environment}}"

# 실제 변경 없이 현재 상태와 ensure 단계를 출력한다.
infra-plan profile environment="prod":
    {{task}} plan --profile "{{profile}}" --environment "{{environment}}"

# AWS, RunPod, runtime binding과 EC2 asset을 로컬에서 수렴한다.
infra-ensure profile environment="prod":
    {{task}} ensure --profile "{{profile}}" --environment "{{environment}}"

# 비밀값을 제외한 AWS, RunPod, 활성 release 상태를 출력한다.
infra-status profile environment="prod":
    {{task}} status --profile "{{profile}}" --environment "{{environment}}"

# 실제 변경 없이 폐기 범위와 순서를 출력한다.
infra-destroy-plan profile environment="prod":
    {{task}} destroy-plan --profile "{{profile}}" --environment "{{environment}}"

# 프로젝트 비용 리소스를 폐기한다. 정확한 confirm 문자열이 필요하다.
infra-destroy profile confirm="DESTROY workshield-prod" environment="prod":
    {{task}} destroy --profile "{{profile}}" --environment "{{environment}}" --confirm "{{confirm}}"

# 프로젝트 stack이 모두 없는 경우 Access/CDK bootstrap까지 폐기한다.
infra-purge profile confirm="PURGE workshield-prod-bootstrap" environment="prod":
    {{task}} purge --profile "{{profile}}" --environment "{{environment}}" --confirm "{{confirm}}"

# Git 비추적 원본을 AWS Secrets Manager runtime secret에 동기화한다.
infra-secrets-sync profile environment="prod":
    {{task}} secrets-sync --profile "{{profile}}" --environment "{{environment}}"

# 지원 secret을 생성·회전하고 candidate/consumer health를 검증한다.
infra-secrets-rotate name profile environment="prod":
    {{task}} secrets-rotate "{{name}}" --profile "{{profile}}" --environment "{{environment}}"

# latest image를 적용할 RunPod candidate를 검증한 뒤 binding을 전환한다.
infra-runpod-replace target profile environment="prod":
    {{task}} runpod-replace "{{target}}" --profile "{{profile}}" --environment "{{environment}}"

# allowlist된 비밀 아닌 CDK output만 GitHub Environment Variable로 등록한다.
infra-github-configure profile environment="production" infra_environment="prod":
    {{task}} github-configure --profile "{{profile}}" --environment "{{infra_environment}}" --github-environment "{{environment}}"

# [원클릭 생성] 사전 점검, AWS Bootstrap, 전체 인프라 프로비저닝을 한 번에 실행한다.
infra-up profile environment="prod":
    just infra-check "{{environment}}"
    just infra-bootstrap "{{profile}}" "{{environment}}"
    just infra-ensure "{{profile}}" "{{environment}}"
    just infra-status "{{profile}}" "{{environment}}"

