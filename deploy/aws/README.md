# WorkShield AWS 배포 도구

이 디렉터리는 AWS 배포에 필요한 CDK, Docker Compose, Nginx 및 운영 스크립트만
관리한다. 애플리케이션 Dockerfile은 각각 `api/`, `mcp/`에 둔다.

## 계정 없이 가능한 검증

```bash
just aws-synth
just aws-compose-config
just aws-build-api
just aws-build-mcp
```

`env/prod.env.example`은 Compose 문법 검사 전용 예시다. 실제 운영에서는
`/opt/workshield/secrets/`의 root 전용 환경 파일과 AWS Secrets Manager에서
가져온 값으로 대체한다. 예시의 origin header와 이미지 tag는 운영 값으로
사용하면 안 된다.

`NGINX_IMAGE`는 반드시 Docker Hub 공식 Nginx의 digest reference여야 한다.
예시의 all-zero digest는 검사 전용 placeholder이며 pull할 수 없다.

CDK synth 전에 `cd iac && uv sync --no-dev && npm install`로 Python virtual
environment와 고정 CLI를 준비한다. `cdk.json`은 그 virtual environment의
Python을 사용하므로 전역 CDK·Python 설치에 의존하지 않는다.

CDK는 기본적으로 `config/prod.example.json`을 사용해 계정 없이 synth한다.
실제 배포 전에는 이를 복사한 Git 비추적 `config/prod.json`에 account, region,
단일 availability zone, origin domain, hosted zone, CloudFront origin-facing
managed prefix list ID를 입력하고 다음처럼 실행한다.

```bash
cd deploy/aws/iac
npm exec cdk -- synth --context config=../config/prod.json
```

`bootstrap/github-oidc-role.yaml`은 OIDC provider와 deploy/execution role의
최초 생성용 CloudFormation template다. CDK stack보다 먼저 관리자 session으로
배포한다.

## 스크립트 경계

- `bootstrap/bootstrap.sh`: GitHub OIDC와 CDK bootstrap의 관리자 진입점
- `scripts/put-secrets.sh`: stdin 또는 숨김 입력으로 Secrets Manager에 비밀 등록
- `scripts/put-parameters.sh`: allowlist 기반 비밀 아닌 Parameter Store 값 등록
- `scripts/write-deployment-config.sh`: GitHub Environment 값으로 Git 비추적 CDK config 생성
- `scripts/set-runtime-parameters.sh`: GHCR·Nginx·origin의 runtime parameter 갱신
- `scripts/install-runtime-assets.sh`: SSM으로 EC2에 secret 없는 release 자산 설치
- `scripts/deploy-containers.sh`: SSM에서 실행할 container release와 자동 복구
- `scripts/dispatch-ssm-command.sh`: runner에서 release SHA만 SSM document에 전달
- `scripts/deploy-web.sh`: 검증된 web build의 S3 배포와 CloudFront invalidation
- `scripts/destroy-project.sh`: WorkShield 소유 자원의 확인형 폐기

최초 운영 배포 전에 Foundation stack을 만든 뒤 다음 명령으로 모든 runtime
secret을 등록한다. 값은 GitHub Actions input이나 command argument로 전달하지
않는다.

```bash
deploy/aws/scripts/put-secrets.sh --secret vllm --generate
deploy/aws/scripts/put-secrets.sh --secret embed --generate
deploy/aws/scripts/put-secrets.sh --secret origin-header --generate
deploy/aws/scripts/put-secrets.sh --secret law
```

`runtime-parameters.example.json`은 형식 예시다. `NGINX_IMAGE`에는 실제
공식 Nginx immutable digest를 사용해야 하며, workflow는 GHCR owner·origin
domain과 함께 `set-runtime-parameters.sh`로 값을 갱신한다.
