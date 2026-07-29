# AWS 배포 구현 계획

이 문서는 배포 구성을 저장소에 구현하는 순서와 구현 전에 준비할 도구·계정
정보를 정리한다. 운영 배포가 완성된 뒤의 반복 절차는
[운영 Runbook](operations-runbook.md)을 따른다.

> 환경 점검일: 2026-07-29  
> 점검 workspace: `SKN30-4th-2Team`

## 1. 구현 원칙

- 실제 AWS 계정과 비밀이 없어도 가능한 저장소 구현을 먼저 완료한다.
- AWS 리소스 생성은 사용자가 account, region, domain을 확정한 뒤 수행한다.
- 비밀값은 채팅, GitHub issue, Git, workflow 입력값으로 전달하지 않는다.
- 비밀 등록 script가 사용자의 안전한 stdin에서 값을 받아 Secrets Manager에
  직접 저장하도록 한다.
- application image는 GHCR에만 게시한다.
- CDK의 `DockerImageAsset`을 사용하지 않는다.
- AWS·RunPod 변경 workflow는 수동 실행만 허용한다.
- RunPod 상태는 로컬 `.env`가 아니라 AWS Parameter Store를 기준으로 한다.
- live 배포 전에 CDK synth, Docker build, Compose config, workflow 정적 검사를
  로컬 또는 CI에서 완료한다.

## 2. 현재 로컬 도구 상태

2026-07-29 기준 점검 결과다.

| 도구 | 상태 | 확인값 | 조치 |
| --- | --- | --- | --- |
| Git | 준비됨 | `2.34.1` | 없음 |
| Docker CLI | 준비됨 | `29.3.1` | daemon 접근은 사용자 terminal에서 재확인 |
| Docker Compose | 준비됨 | `v5.1.1` | 없음 |
| Node.js | 준비됨 | `v24.14.1` | CDK 요구사항 충족 |
| npm | 준비됨 | `11.11.0` | 없음 |
| Python | 준비됨 | API·MCP venv `3.13.12` | system Python 3.10은 문제 없음 |
| uv | 준비됨 | `0.11.2` | 없음 |
| just | 준비됨 | `1.54.0` | 없음 |
| OpenSSL | 준비됨 | `3.0.2` | 비밀 생성에 사용 가능 |
| RunPod CLI | 준비됨 | `2.7.2` | 기존 네 Pod script를 CI 호환으로 확장 |
| AWS CLI v2 | 설치 필요 | 미설치 | 사용자가 설치 |
| `jq` | 설치 필요 | 미설치 | 사용자가 설치 |
| GitHub CLI | 선택 설치 | 미설치 | 초기 Environment 설정·확인에 유용 |
| AWS CDK CLI | 저장소에 추가 예정 | 전역 미설치 | npm devDependency로 version 고정 |

CDK 공식 가이드는 Node.js 22 이상과 Python 3.9 이상을 요구한다. 현재
Node.js와 프로젝트 Python은 조건을 충족한다. CDK CLI는 전역 설치하지 않고
`deploy/aws/iac/package.json`에 고정해 `npm exec cdk`로 실행한다.

Docker daemon 확인은 Codex 실행 격리에서 socket 접근이 차단되어 완료하지
못했다. 사용자 terminal에서 다음 명령이 성공해야 한다.

```bash
docker info
docker compose version
```

## 3. 사용자 설치 요청

### 필수

1. AWS CLI v2
2. `jq`

Ubuntu에서 설치 후 다음이 성공해야 한다.

```bash
aws --version
jq --version
```

AWS CLI는 package manager의 오래된 v1 대신 AWS CLI v2 설치를 권장한다.

### 선택

- GitHub CLI `gh`
- `shellcheck`
- `actionlint`

GitHub Environment와 package visibility는 웹 UI로도 설정할 수 있으므로
`gh`는 필수가 아니다. `shellcheck`와 `actionlint`는 로컬 편의를 위한
도구이며 CI에서 고정 version으로 실행할 수 있다.

## 4. 사용자에게 필요한 AWS 권한

최초 bootstrap을 수행하는 사람은 AWS SSO 또는 통제된 관리자 session으로
다음 리소스를 만들 수 있어야 한다.

- IAM OIDC provider, role, policy
- CloudFormation과 CDK bootstrap
- EC2, EBS, Elastic IP, security group
- S3, CloudFront
- Route 53 record
- Secrets Manager, SSM Parameter Store, Systems Manager
- CloudWatch log group과 alarm

장기 IAM user access key는 만들 필요가 없다. 로컬 AWS CLI 인증은 AWS SSO를
권장한다.

```bash
aws configure sso
aws sso login --profile <profile>
aws sts get-caller-identity --profile <profile>
```

bootstrap용 권한과 GitHub Actions deploy role의 운영 권한은 분리한다.

## 5. 사용자 확정이 필요한 비밀이 아닌 값

다음 값은 구현 전 또는 parameter 파일 작성 전에 확정해야 한다.

| 항목 | 예시·권장 | 필요한 이유 |
| --- | --- | --- |
| 실제 배포 GitHub repository | `Hong1008/SKN30-4th-2Team` | OIDC trust subject |
| GHCR owner | 수동 workflow 입력, owner만 입력 | image URI |
| GHCR visibility | `public` 확정 | EC2 anonymous pull |
| AWS account ID | `deploy/aws/config/prod.json`에 입력 | CDK environment, OIDC role |
| AWS region | `ap-northeast-2` | 모든 regional resource |
| CDK app/stack prefix | `workshield-prod` 권장 | 리소스 이름 |
| origin domain | ip갱신 필요, `workshield.duckdns.org` | CloudFront→EC2 TLS |
| Route 53 hosted zone ID | Route 53 사용, 실제 zone 준비 | DNS-01과 origin record |
| GitHub Environment | `production` | 배포 승인과 OIDC subject |
| required reviewer | 정상 배포는 선택, 전체 폐기는 `Hong1008` | 운영 작업 승인 |
| VLLM base URL·model ID | workflow가 Pod 생성 후 자동 기록 | API runtime 설정 |
| Embedder·Reranker 연결 | Pod base URL, workflow가 자동 기록 | MCP runtime 설정 |

실제 배포 repository는 다음과 같이 확정했다.

```text
Hong1008/SKN30-4th-2Team
```

GHCR public 사용은 승인됐다. package를 public으로 바꾸면 다시 private으로
되돌릴 수 없으므로 최초 게시 전에 image layer와 MCP corpus에 비공개
데이터가 없는지는 계속 확인한다.

## 6. 사용자가 보유해야 하지만 전달하지 않을 비밀

다음 값은 사용자가 발급·보유해야 한다. 값을 Codex 채팅이나 Git에 붙여 넣지
않고 구현할 `put-secrets.sh` 또는 AWS Console에서 직접 등록한다.

| 비밀 | 필수 여부 | 준비 방법 |
| --- | --- | --- |
| `RUNPOD_API_KEY` | 필수 | 운영 전용 key 발급 후 GitHub Environment Secret 등록 |
| `LAW_OC` | 필수, 보유 확인 | AWS Secrets Manager에 안전하게 등록 |
| `HUGGING_FACE_TOKEN` | 조건부 | gated model 또는 rate limit 대응 시 발급 |
| `GHCR_READ_TOKEN` | private package일 때만 | PAT classic `read:packages` |

다음 값은 사용자가 미리 전달할 필요가 없으며 배포 script가 생성할 수 있다.

| 비밀 | 생성 |
| --- | --- |
| `VLLM_API_KEY` | `openssl rand -hex 32` |
| Embedder API key | `openssl rand -hex 32` |
| CloudFront origin header | `openssl rand -hex 32` |

기존 RunPod Pod가 이미 `VLLM_API_KEY`를 사용 중이면 새 값을 임의로 생성하지
않고 기존 Pod와 API를 함께 회전해야 한다.

## 7. 구현 단계

### 1단계: 저장소 골격

사용자 계정 정보 없이 진행할 수 있다.

- `deploy/aws/` 디렉터리 생성
- CDK Python project와 npm 기반 CDK CLI version pin
- Compose, Nginx, CloudFront Function 디렉터리 생성
- bootstrap·deploy·rollback script entrypoint 생성
- `.gitignore`에 CDK output, runtime env, certificate, local parameter 제외
- root `justfile`에 synth·build·config 검사 명령 추가

완료 기준:

- secret 없는 example 설정만 Git 추적
- `npm exec cdk synth` 진입점 존재
- shell script가 실제 secret을 요구하지 않고 `--help` 또는 dry-run 가능

### 2단계: 컨테이너 패키징

- `api/Dockerfile` 작성
- 기존 `mcp/Dockerfile` 운영 적합성 확인
- `.dockerignore` 작성
- `compose.prod.yaml` 작성
- Nginx TLS·origin header·SSE 설정 작성
- API와 MCP health check 정의
- API의 MCP URL을 `http://mcp:8000/mcp`로 설정
- 영속 SQLite·업로드 volume mount 정의

완료 기준:

- API·MCP image local build
- Compose config 해석 성공
- image에 `.env`, SQLite 사용자 데이터, key가 포함되지 않음
- 단일 worker 설정 확인

### 3단계: AWS CDK

- bootstrap CloudFormation template 작성
- foundation stack 작성
- service stack 작성
- CloudFront behaviors와 SPA Function 작성
- EC2 instance role, SSM document, EBS mount 작성
- origin domain·TLS 준비 순서를 stack dependency에 반영
- application image ECR construct를 사용하지 않음

완료 기준:

- 사용자 값은 context 하드코딩이 아닌 parameter·Environment로 분리
- `cdk synth` 성공
- secret 값이 template output에 없음
- destructive resource policy가 명시됨

### 4단계: 기존 RunPod script의 CI 호환 확장

- `deploy/llm_pod/deploy_llm_pod.py`
- `deploy/llm_pod/rm_llm_pod.py`
- `mcp/deploy/deploy_embed_pod.py`
- `mcp/deploy/rm_embed_pod.py`
- secret 없는 JSON output
- 명시적 Pod ID 입력과 `ignore-not-found`
- `.env` 비변경 CI mode
- Pod readiness 대기와 제한 시간
- Parameter Store 상태 저장
- VLLM key 로그 출력 제거
- Embedder·Reranker API key 인증 구현과 MCP header 연동

완료 기준:

- 같은 명령을 반복해도 정상 Pod를 중복 생성하지 않음
- 실패 시 해당 실행에서 생성한 Pod만 삭제
- 모든 secret이 stdout과 command 표시에 없음
- 무인증 vLLM·Embedder 요청이 거부됨
- 삭제는 저장된 Pod ID를 사용하고 없는 Pod를 성공 처리

세부 CLI와 상태 계약은 [RunPod 자동화](runpod-automation.md)를 따른다.

### 5단계: GitHub Actions와 GHCR

- `ci.yml`
- `deploy-production.yml`
- `rollback-production.yml`
- `destroy-production.yml`
- submodule recursive checkout
- API·MCP·Embedder 병렬 build
- `GITHUB_TOKEN`으로 GHCR push
- SHA tag와 OCI source/revision label
- GitHub OIDC AWS role assume
- production·production-destroy Environment와 공통 concurrency 적용
- Action commit SHA pin
- 모든 변경 workflow는 `workflow_dispatch`만 사용
- RunPod 생성·자동 바인딩·삭제 job 연결

완료 기준:

- PR에서는 AWS credential과 package push가 없음
- main push에서 image 게시·운영 배포가 자동 실행되지 않음
- `latest`가 배포 source가 아님
- 정상 재배포가 기존 정상 RunPod를 재사용
- 전체 폐기가 정확한 확인 문자열과 Environment 승인을 요구

### 6단계: 배포·비밀·폐기 script

- Secrets Manager 입력 script
- Parameter Store 설정 script
- SSM container deploy script
- S3 web deploy와 CloudFront invalidation
- health check와 활성 release 기록
- 이전 SHA rollback
- RunPod와 AWS 전체 project resource 폐기
- stdout 비밀 노출 방지

완료 기준:

- SSM command parameter에 secret 원문 없음
- EC2 root 전용 env file 생성
- 실패 시 이전 container 유지 또는 복구
- 사용자 데이터 volume을 삭제하는 명령이 일반 배포에 없음
- destroy가 project 소유 resource만 삭제하고 잔존 자원을 보고

### 7단계: 실제 계정 연결

이 단계부터 사용자 AWS account와 domain이 필요하다.

1. 사용자 AWS SSO login
2. OIDC·CDK bootstrap
3. GitHub production Environment 설정
4. GitHub에 `RUNPOD_API_KEY` Environment Secret 등록
5. Foundation stack 배포 후 `put-secrets.sh`로 `vllm`, `embed`, `origin-header`, `law` 등록
6. 최초 GHCR image 게시와 public visibility 확정
7. foundation stack 배포
8. RunPod Pod 자동 생성·상태 확인·binding
9. origin DNS·인증서 준비
10. service stack과 CloudFront 배포
11. 최초 container·web release
12. 운영 URL과 활성 release 기록

## 8. 사용자 응답 반영 결과

| 항목 | 반영 |
| --- | --- |
| repository | `Hong1008/SKN30-4th-2Team` |
| trigger | 운영 변경은 수동 실행, main push 자동 배포 없음 |
| GHCR | owner만 workflow 입력, public package |
| AWS | account ID는 설정 파일, region은 `ap-northeast-2` |
| DNS | Route 53 사용 |
| reviewer | 정상 배포 선택, 폐기는 `Hong1008` 승인 |
| Embedder·Reranker | Pod base URL |
| vLLM | workflow가 URL·model ID를 자동 바인딩, API key는 안전한 secret 등록 script로 생성 |
| LAW_OC | 보유 |
| 폐기 | 생성한 project AWS·RunPod 자원 자동 삭제 |

## 9. 지금 사용자에게 필요한 조치

저장소 구현은 계속할 수 있다. 실제 배포 전 사용자 조치는 다음과 같다.

1. AWS CLI v2와 `jq` 설치
2. 사용자 terminal에서 `docker info` 성공 확인
3. RunPod 운영 전용 API key 발급 후 Pod create/get/list/delete 권한 확인
4. GitHub `production`과 `production-destroy` Environment 생성
5. `RUNPOD_API_KEY`를 Environment Secret으로 등록
6. GitHub Environment에 account·AZ·domain·hosted zone·Nginx digest 변수를 입력
7. 실제 origin domain과 Route 53 hosted zone ID 준비
8. AWS SSO profile 준비
9. Foundation stack 배포 후 `LAW_OC`와 생성한 runtime secret을 안전한 secret 등록 script로 AWS에 입력

`origin.workshield.com`은 예시이므로 실제 배포 설정으로 사용하지 않는다.
RunPod URL, Pod ID, vLLM model ID와 vLLM API key는 사용자가 미리 준비할 필요가
없다.

## 공식 참고

- [AWS CDK prerequisites](https://docs.aws.amazon.com/cdk/v2/guide/prerequisites.html)
- [AWS CDK bootstrap](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-bootstrap.html)
- [AWS CLI v2 설치](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [GitHub Container registry 인증](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [GitHub package visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)
