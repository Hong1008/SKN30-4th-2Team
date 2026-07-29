# WorkShield 인프라

이 문서는 WorkShield 운영 인프라의 구조와 책임 경계의 기준 문서다. 로컬
운영자는 인프라를 생성·변경·제거하고, GitHub Actions는 검증된 애플리케이션
artifact를 기존 리소스에 배포한다.

## 구성

```text
사용자
  │ HTTPS
  ▼
CloudFront
  ├─ /*        → private S3 web bucket (OAC)
  ├─ /api/*    → EC2 Nginx → API container
  └─ /health/* → EC2 Nginx → API health
                              ├─ RunPod vLLM Pod
                              └─ MCP container → RunPod Embed/Rerank Pod
```

- API와 MCP는 단일 EC2에서 Docker Compose로 실행한다.
- EC2 origin은 Elastic IP와 DuckDNS 이름을 사용한다. CloudFront에서 origin까지
  HTTPS를 적용하고, CloudFront origin-facing prefix list와 비밀 origin header를
  함께 검사한다.
- 정적 Web은 private S3 bucket에 저장하고 CloudFront OAC로만 공개한다.
- 사용자 데이터와 임시 업로드는 암호화된 EBS에 저장한다.
- 운영 접속은 SSM Session Manager를 사용하며 SSH inbound를 열지 않는다.

## 책임

| 주체 | 책임 |
| --- | --- |
| 로컬 운영자 | AWS bootstrap, CDK plan/deploy/destroy, EC2 runtime asset 설치, RunPod 생성·교체·제거, runtime secret 등록·회전 |
| GitHub CI | test, lint, image build 검증, Compose config, CDK synth |
| GitHub container 배포 | 기존 GHCR image를 기존 EC2에 SSM Run Command로 배포·롤백 |
| GitHub Web 배포 | versioned S3 artifact 게시·승격·롤백, CloudFront invalidation |
| EC2 instance role | 지정 Secrets Manager·SSM 값 읽기, CloudWatch 전송 |
| GitHub deploy role | 지정 SSM Document 실행, 지정 S3 bucket 배포, 지정 CloudFront distribution invalidation |

GitHub deploy role은 CloudFormation·EC2·IAM을 변경하거나 Secrets Manager 값을
읽지 않는다. GitHub에는 RunPod 관리 키와 애플리케이션 runtime secret을
저장하지 않는다.

## 공개 실행 인터페이스

루트 [`justfile`](../../../justfile)만 로컬 운영 인터페이스다. `infra/` 내부
Python 모듈과 provider 스크립트는 구현 세부사항이므로 직접 실행하지 않는다.

주요 명령은 다음과 같다.

```text
just infra-init
just infra-check
just infra-bootstrap profile=<profile>
just infra-plan profile=<profile> environment=prod
just infra-ensure profile=<profile> environment=prod
just infra-status profile=<profile> environment=prod
just infra-runpod-replace llm|embed|all profile=<profile> environment=prod
just infra-destroy-plan profile=<profile> environment=prod
just infra-destroy profile=<profile> environment=prod confirm="DESTROY workshield-prod"
just infra-purge profile=<profile> confirm="PURGE workshield-prod-bootstrap"
```

`infra-plan`과 `infra-destroy-plan`은 변경 없이 계획만 출력한다. 실제 생성은
`infra-ensure`, 일반 폐기는 `infra-destroy`, 공유 bootstrap·OIDC까지 제거하는
작업은 `infra-purge`로 분리한다.

## 수렴과 소유권

모든 변경 명령은 다음 순서로 동작한다.

```text
preflight → lock → discover → plan → apply → verify → journal
```

상태 판정은 다음 계약을 따른다.

| 발견 상태 | 동작 |
| --- | --- |
| 없음 | 생성 |
| 존재하고 설정 일치 | 재사용 |
| 존재하고 안전한 변경 가능 | 갱신 |
| 소유권 불명 또는 복수 후보 | 중단 |
| immutable 설정 불일치 | 명시적 교체 전까지 중단 |

AWS 리소스는 결정적 이름과 `Project`, `Environment`,
`ManagedBy=workshield-infra` tag로 재발견한다. 로컬 state는 캐시와 실패 보상
journal이지 소유권의 유일한 근거가 아니다. 실패 보상은 이번 실행에서 만든
리소스에만 적용한다.

RunPod Pod 이름만으로는 소유권을 확정하지 않는다. 이름, template ID, GPU,
예상 설정과 실행 상태를 함께 확인하며 후보가 둘 이상이면 중단한다.

## MCP submodule 경계

MCP submodule의 `deploy_embed_pod.py`, `rm_embed_pod.py`와 대응하는 `just`
명령은 MCP 저장소를 단독 실행할 때 필요하므로 유지한다.

- MCP 저장소는 Embed/Rerank worker, `Pod.Dockerfile`, 단독 Pod lifecycle
  스크립트와 이미지 게시 workflow를 소유한다.
- 부모 저장소는 해당 스크립트의 JSON 출력 계약을 사용해 전체
  ensure/status/destroy, AWS runtime binding, lock과 journal을 관리한다.
- 부모 저장소 사용자는 MCP lifecycle 스크립트를 직접 호출하지 않는다.
- 부모 모드에서 MCP 스크립트는 SSM이나 AWS 상태를 수정하지 않는다.

## 문서

- [처음 설치](getting-started.md)
- [로컬 프로비저닝](provisioning.md)
- [애플리케이션 배포와 롤백](../operations/deploy.md)
- [비밀 관리](../operations/secrets.md)
- [장애 대응](../operations/troubleshooting.md)
