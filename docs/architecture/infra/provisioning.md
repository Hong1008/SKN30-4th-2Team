# 로컬 프로비저닝

AWS와 RunPod의 생성·변경·제거는 운영자 로컬 환경에서만 수행한다. GitHub
Actions로 CDK나 RunPod lifecycle을 실행하지 않는다.

## 실행 전 확인

```bash
just infra-check
just infra-status <profile> prod
just infra-plan <profile> prod
```

- AWS identity의 account가 설정과 일치해야 한다.
- 변경 중인 같은 account/region/environment lock이 없어야 한다.
- `prod.json`에는 비밀이 없어야 하고 `prod.secrets.env`는 Git 비추적 상태여야
  한다.
- 기존 리소스의 이름과 `Project`, `Environment`, `ManagedBy` tag를 확인한다.
- RunPod 후보가 복수이거나 template 소유권을 확인할 수 없으면 진행하지
  않는다.

## Bootstrap

```bash
just infra-bootstrap <profile>
```

Bootstrap은 CDK bootstrap과 GitHub OIDC 접근 기반을 준비하는 별도 단계다.
일반 `infra-ensure`나 `infra-destroy`에서 공유 bootstrap을 제거하지 않는다.
처음 한 번 실행하거나 bootstrap 정책을 의도적으로 갱신할 때만 사용한다.

Bootstrap은 기존 legacy broad policy를 제거하고 repository/environment가
고정된 trust와 권한 없는 role을 준비한다. 이후 `infra-ensure`의 Service
stack이 다음 application deploy 범위만 연결하는지 확인한다.

- 고정 SSM Document와 대상 instance의 Run Command
- 지정 Web bucket object 작업
- 지정 CloudFront distribution invalidation
- 명령과 배포 상태 확인에 필요한 최소 read

CloudFormation·EC2·IAM 변경, Secrets Manager 값 조회, SSM Parameter 변경
권한은 GitHub role에 부여하지 않는다.

## 생성과 수렴

```bash
just infra-ensure <profile> prod
```

`infra-ensure`는 lock을 획득하고 비어 있는 `VLLM_API_KEY`와
`RUNPOD_EMBED_API_KEY`를 로컬 secret 파일에 원자적으로 생성한 뒤 AWS
Foundation, RunPod, runtime secret과 binding, AWS Service, EC2 runtime
asset 순서로 수렴한다. 이미 존재하는 호출 키와 일치하는 리소스는 재사용한다.

Foundation과 Service stack 분리는 다음 순서 의존성을 유지하기 위한 것이다.

1. instance role, 네트워크, Elastic IP, secret/parameter namespace 준비
2. 로컬 Pod 호출 키 자동 바인딩과 DuckDNS 준비
3. 같은 호출 키를 사용하는 RunPod endpoint readiness·인증 검증
4. 검증된 호출 키를 Secrets Manager에 동기화하고 runtime binding 기록
5. EC2, Web bucket, CloudFront와 고정 SSM Document 준비
6. origin TLS와 secret 없는 Compose·Nginx·release runtime asset 설치

EC2 runtime asset 설치는 로컬 `infra-ensure`만 수행한다. GitHub 배포
workflow는 이 파일을 변경하지 않는다.

## 상태 확인

```bash
just infra-status <profile> prod
```

상태 출력에는 secret 값을 포함하지 않는다. 다음을 확인한다.

- stack과 관리 리소스의 소유권·상태
- EC2 SSM 연결과 origin health
- RunPod ID, template ID, 상태와 endpoint 존재 여부
- 현재 runtime binding과 활성 container tag/digest
- 실행 중 Pod가 기록한 digest와 현재 `latest` digest 차이

registry 조회가 불가능하면 digest 비교는 `unknown`으로 표시하며 Pod를
자동 교체하지 않는다.

## RunPod 교체

RunPod image reference는 다음 mutable tag를 사용한다.

```text
vllm/vllm-openai:latest
ghcr.io/<owner>/<mcp-repository>/embed-rerank:latest
```

`latest` 갱신은 실행 중인 Pod를 바꾸지 않는다. 교체는 명시적으로 실행한다.

```bash
just infra-runpod-replace llm <profile> prod
just infra-runpod-replace embed <profile> prod
just infra-runpod-replace all <profile> prod
```

교체는 candidate 생성, readiness와 인증 확인, runtime binding 전환, 기존 Pod
삭제 순서다. Embed/Rerank endpoint는 인증 요청이 성공하고 무인증 요청이
`401` 또는 `403`이어야 한다. 검증 실패 시 기존 binding과 Pod를 유지하고
이번 실행에서 만든 candidate만 정리한다.

MCP submodule의 `deploy_embed_pod.py`, `rm_embed_pod.py`는 단독 실행 계약을
유지한다. 부모 저장소에서는 root `just` 명령이 JSON 모드로 호출하므로 직접
실행하지 않는다.

## 비밀과 GitHub 변수

```bash
just infra-secrets-sync profile=<profile> environment=prod
just infra-secrets-rotate <name> profile=<profile> environment=prod
just infra-github-configure profile=<profile> environment=production
```

- secret 동기화는 로컬 원본을 Secrets Manager에 쓰며 값을 출력하지 않는다.
- 자동 pending/candidate 회전은 `vllm`, `embed` 이름을 지원한다. 외부
  공급자가 발급하는 값은 원본을 갱신한 뒤 동기화하고 별도 검증한다.
- GitHub 설정에는 region, role ARN, SSM Document, bucket, distribution ID 등
  allowlist된 비밀 아닌 output만 보낸다.
- RunPod 관리 키, 모델 호출 키, 법령 API key와 origin header는 GitHub에
  보내지 않는다.

`infra-github-configure`를 실행하는 동안에는 repository Environment Variable
관리 권한을 가진 `GH_TOKEN`을 process environment로만 제공한다. 이 토큰은
GitHub Environment Variable이나 프로젝트 파일에 저장하지 않는다.

자세한 회전 순서는 [비밀 관리](../operations/secrets.md)를 따른다.

## 폐기

먼저 실제 변경 없는 폐기 계획을 확인한다.

```bash
just infra-destroy-plan profile=<profile> environment=prod
```

비용 리소스와 보존 리소스를 확인한 뒤 정확한 확인 문자열로 실행한다.

```bash
just infra-destroy \
  profile=<profile> \
  environment=prod \
  confirm="DESTROY workshield-prod"
```

일반 폐기는 RunPod Pod, Service stack, Foundation stack 순서로 수행하고
프로젝트 secret은 복구 유예를 둔 삭제 대상으로 처리한다. 소유권을 확인할
수 없거나 예상 밖 리소스가 발견되면 자동 삭제하지 않는다. GHCR package,
GitHub Environment, DuckDNS 계정, 공유 OIDC와 CDK bootstrap은 기본 보존한다.
모든 소유 Pod 삭제와 AWS secret 삭제 예약까지 성공한 뒤 로컬
`VLLM_API_KEY`, `RUNPOD_EMBED_API_KEY` 값만 비우며 관리 키와 외부 발급
secret은 보존한다. 폐기 도중 실패하면 재시도와 복구를 위해 호출 키를
보존한다.

공유 bootstrap과 OIDC까지 제거하는 작업은 별도 명령이다.

```bash
just infra-purge \
  profile=<profile> \
  confirm="PURGE workshield-prod-bootstrap"
```

`infra-purge`는 다른 환경이나 저장소가 공유하지 않는다는 사실을 확인한
경우에만 실행한다.
