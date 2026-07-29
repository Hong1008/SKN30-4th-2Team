# 인프라 장애 대응

먼저 변경 없는 상태 확인을 실행한다.

```bash
just infra-check
just infra-status profile=<profile> environment=prod
```

로그를 공유할 때 secret, authorization header, presigned URL, 전체 environment
출력을 제거한다.

## 로컬 실행

| 현상 | 확인과 조치 |
| --- | --- |
| `infra-check` 도구 실패 | [설치 가이드](../infra/getting-started.md)의 버전 명령과 PATH 확인 |
| submodule 파일 없음 | `git submodule update --init --recursive` |
| AWS identity 불일치 | `aws sts get-caller-identity --profile <profile>` 확인 후 올바른 SSO/MFA session 갱신 |
| credential 만료 | `aws sso login` 또는 MFA session profile 재발급 |
| lock 충돌 | 같은 환경 작업이 실행 중인지 확인한다. 프로세스 확인 없이 lock 파일을 지우지 않는다. |
| 소유권 불명 | 이름과 `Project`, `Environment`, `ManagedBy` tag를 확인한다. 자동 adopt/delete하지 않는다. |
| 복수 후보 | 어떤 리소스가 관리 대상인지 수동 식별하고 불필요한 후보를 별도 승인 절차로 정리한다. |

## CDK와 AWS

| 현상 | 확인과 조치 |
| --- | --- |
| bootstrap 누락 | 대상 account/region을 확인하고 `just infra-bootstrap profile=<profile>` |
| CloudFormation rollback | stack event의 첫 실패 원인을 확인한다. 보존된 secret이나 IAM deny를 먼저 해결한다. |
| 기존 secret 이름 충돌 | 실제 값이 있는 secret을 삭제하지 않는다. 소유권과 recovery 상태를 확인해 복원 또는 명시적 정리한다. |
| EC2가 SSM에 없음 | SSM agent, instance role, outbound 443, VPC DNS를 확인한다. SSH를 임시 개방하지 않는다. |
| SSM 배포 실패 | command 단계, 고정 Document version, 대상 instance와 활성 이전 digest를 확인한다. |
| GitHub OIDC 실패 | trust의 repository/Environment subject, audience, Environment branch rule을 확인한다. 장기 AWS key로 우회하지 않는다. |

## Container와 GHCR

| 현상 | 확인과 조치 |
| --- | --- |
| image tag 없음 | `publish-containers.yml` 결과와 API·MCP 두 package를 확인한다. 배포 중 rebuild하지 않는다. |
| tag 충돌 | 같은 tag가 다른 digest를 가리키면 새 tag로 다시 게시한다. 기존 tag를 덮어쓰지 않는다. |
| EC2 pull 실패 | package visibility와 digest를 확인한다. private 정책이면 read-only credential 경로를 별도로 설계한다. |
| API 재시작 | MCP health, Docker DNS `mcp`, allowed host, runtime secret 이름을 확인한다. |
| MCP `421` | FastMCP transport security allowlist에 Compose service host가 포함됐는지 확인한다. |
| 배포 health 실패 | 자동 복구된 이전 digest를 확인하고 새 Web 배포를 중단한다. |

## RunPod

| 현상 | 확인과 조치 |
| --- | --- |
| GPU 가용성 없음 | 설정된 대체 GPU 정책을 검토한다. 임의 GPU로 자동 변경하지 않는다. |
| Pod는 `RUNNING`, endpoint는 `502` | 모델 초기화 중일 수 있다. readiness timeout까지 기다리고 binding을 먼저 전환하지 않는다. |
| 무인증 요청이 `200` | 보안 실패다. candidate를 활성화하지 않고 worker image와 API key 설정을 수정한다. |
| `latest` digest 불일치 | 정상적인 drift 보고다. 검토 후 `just infra-runpod-replace`로 명시적 교체한다. |
| 동일 이름 Pod가 여러 개 | 소유권 불명으로 중단한다. 이름만 보고 자동 삭제하지 않는다. |
| MCP submodule JSON 오류 | submodule revision과 standalone script의 JSON 출력 계약을 확인한다. |

## Web과 CloudFront

| 현상 | 확인과 조치 |
| --- | --- |
| rollback artifact 없음 | S3 `releases/<tag>/`와 manifest를 확인한다. source를 자동 rebuild하지 않는다. |
| 변경이 바로 보이지 않음 | invalidation 완료와 브라우저 cache를 확인한다. |
| CloudFront `502` | origin DNS, 인증서 만료, Nginx, origin header, prefix list를 확인한다. |
| API 오류가 HTML `200` | distribution 전체 403/404 SPA fallback을 제거하고 S3 behavior의 rewrite만 사용한다. |
| SSE 조기 종료 | Nginx buffering/cache, CloudFront timeout, heartbeat 주기를 확인한다. |

## 실패 후 정리

- journal에서 이번 실행에 생성된 리소스와 기존 리소스를 구분한다.
- 자동 보상은 이번 실행 생성분에만 허용한다.
- 기존 정상 Pod, binding, active digest와 데이터 volume을 삭제하지 않는다.
- `docker compose down -v`, 강제 secret 삭제, bootstrap purge를 장애 복구
  수단으로 사용하지 않는다.
- 폐기 실패 시 `infra-status`와 `infra-destroy-plan`을 다시 실행해 잔존
  비용 리소스를 확인한다.

해결 후에는 비밀값이 아닌 원인, 영향, 복구 방식과 후속 조치만 운영 이력에
기록한다.

