# WorkShield AWS 배포 문서

이 문서는 WorkShield 운영 배포 문서의 진입점이다. 배포 구성과 운영 절차만
다루며 성능·동시성·부하 검증 기준은 다루지 않는다.

## 확정 구성

| 영역 | 결정 |
| --- | --- |
| 배포 오케스트레이터 | GitHub Actions |
| 컨테이너 레지스트리 | GitHub Container Registry(`ghcr.io`) |
| 인프라 코드 | AWS CDK v2 Python |
| AWS 명령 도구 | 최초 bootstrap, 비밀 등록, SSM 운영 명령에 AWS CLI 사용 |
| 정적 웹 | 비공개 S3 bucket + CloudFront OAC |
| API·MCP | 단일 `t3.small` EC2의 Docker Compose |
| reverse proxy | Nginx |
| EC2 애플리케이션 배포 | AWS Systems Manager Run Command |
| 데이터 저장 | 암호화된 EBS의 SQLite와 임시 업로드 디렉터리 |
| 외부 모델 | RunPod Embedder·Reranker·vLLM |
| RunPod 수명주기 | GitHub Actions에서 Pod 생성·상태 확인·자동 바인딩·삭제 |
| viewer 주소 | CloudFront 기본 도메인 |
| origin TLS | origin 전용 도메인과 공인 인증서, CloudFront `HTTPS only` |
| origin 접근 제한 | CloudFront origin-facing prefix list + 비밀 origin header |
| 운영 접속 | SSM Session Manager, SSH inbound 미사용 |

GitHub Actions는 배포 순서를 조정하는 역할만 맡는다. AWS 리소스 정의의
원본은 CDK 코드이며, 실제 배포 명령은 `deploy/aws/`의 스크립트로 관리한다.
워크플로 YAML 안에 긴 shell 절차를 직접 작성하지 않는다.

## 문서 구성

| 문서 | 책임 |
| --- | --- |
| [AWS 배포 아키텍처](infra/aws-deployment-architecture.md) | AWS 리소스, 네트워크, CDK 경계, Docker Compose 구조 |
| [CI/CD](infra/ci-cd.md) | GitHub Actions trigger, GHCR 이미지, 배포·롤백 파이프라인 |
| [RunPod 자동화](infra/runpod-automation.md) | 기존 Pod 스크립트 확장, 상태 저장, 자동 바인딩·폐기 |
| [비밀 관리](infra/secrets-management.md) | 비밀 발급, 저장 위치, 주입, 회전·폐기 |
| [운영 Runbook](infra/operations-runbook.md) | 최초 설정, 정상 배포, 롤백, 인증서·비밀 운영 절차 |
| [구현 계획](infra/implementation-plan.md) | 구현 순서, 로컬 도구 점검, 사용자 준비·확정 항목 |

배포 구현 시 위 문서를 다음 순서로 읽는다.

1. AWS 배포 아키텍처에서 리소스와 신뢰 경계를 확인한다.
2. 비밀 관리 문서에 따라 계정·키·인증서를 준비한다.
3. RunPod 자동화 문서에서 Pod의 생성·상태·폐기 계약을 확인한다.
4. CI/CD 문서에 따라 GitHub Environment와 workflow를 구성한다.
5. 구현 계획에 따라 저장소 파일과 AWS 연결을 단계적으로 만든다.
6. 운영 Runbook에 따라 최초 배포와 이후 운영을 수행한다.

## 목표 저장소 구조

다음 구조는 구현 목표다. 현재 존재하지 않는 파일은 배포 구현 단계에서
추가한다.

```text
.github/
└─ workflows/
   ├─ ci.yml
   ├─ deploy-production.yml
   ├─ rollback-production.yml
   └─ destroy-production.yml

api/
└─ Dockerfile

mcp/
└─ Dockerfile

deploy/
├─ llm_pod/
└─ aws/
   ├─ README.md
   ├─ compose.prod.yaml
   ├─ bootstrap/
   │  ├─ github-oidc-role.yaml
   │  └─ bootstrap.sh
   ├─ cloudfront/
   │  └─ spa-rewrite.js
   ├─ env/
   │  └─ prod.env.example
   ├─ iac/
   │  ├─ app.py
   │  ├─ cdk.json
   │  ├─ pyproject.toml
   │  └─ stacks/
   │     ├─ foundation_stack.py
   │     └─ service_stack.py
   ├─ nginx/
   │  └─ nginx.conf
   ├─ scripts/
   │  ├─ deploy-containers.sh
   │  ├─ deploy-web.sh
   │  ├─ healthcheck.sh
   │  ├─ put-secrets.sh
   │  ├─ destroy-production.sh
   │  └─ rollback.sh
   └─ ssm/
      └─ deploy-document.yaml
```

서비스 Dockerfile은 서비스 소스 가까이에 둔다. `deploy/aws/`에는 Compose,
reverse proxy, CDK, bootstrap 및 운영 스크립트만 둔다.

## 범위 밖

다음 항목은 이 문서 묶음의 범위가 아니다.

- 모델 품질 평가
- 부하 시험과 최대 접속자 산정
- PostgreSQL·Redis·ALB를 이용한 다중 인스턴스 확장
- 애플리케이션 기능과 API 계약

RunPod Pod 수명주기는 배포 범위에 포함한다. 비용과 삭제 위험 때문에 일반
애플리케이션 재배포와 Pod 교체는 구분하며, 세부 계약은
[RunPod 자동화](infra/runpod-automation.md)를 따른다.
