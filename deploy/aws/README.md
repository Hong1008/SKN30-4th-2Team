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

## 스크립트 경계

- `bootstrap/bootstrap.sh`: GitHub OIDC와 CDK bootstrap의 관리자 진입점
- `scripts/deploy-containers.sh`: SSM에서 실행할 컨테이너 배포 진입점
- `scripts/rollback.sh`: 이전 SHA로의 컨테이너 롤백 진입점

현재 스크립트는 안전한 `--help`/`--dry-run` 인터페이스만 제공한다. AWS API
호출과 secret 주입은 이후 구현 단계에서 추가한다.
