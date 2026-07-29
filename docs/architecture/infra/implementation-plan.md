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
| DNS | DuckDNS (`workshield.duckdns.org`)를 CloudFront origin domain으로 사용 |
| reviewer | 정상 배포 선택, 폐기는 `Hong1008` 승인 |
| Embedder·Reranker | Pod base URL |
| vLLM | workflow가 URL·model ID를 자동 바인딩, API key는 안전한 secret 등록 script로 생성 |
| LAW_OC | 보유 |
| 폐기 | 생성한 project AWS·RunPod 자원 자동 삭제 |

## 2026-07-29 실제 연결 진행 기록

- AWS profile `4th-student`로 account `182116415809`, region `ap-northeast-2`를 확인했다.
- GitHub OIDC provider, `workshield-prod-github-deploy` role, CDKToolkit bootstrap을 생성했다. OIDC trust는 `Hong1008/SKN30-4th-2Team`의 `production`, `production-destroy` Environment만 허용한다.
- GitHub `production` Environment에 AWS account, AZ, deploy role ARN, DuckDNS origin, CloudFront prefix list, Nginx digest 변수를 동기화했다. 동기화 script는 GitHub Environment Variables API의 POST/PATCH 계약으로 보완했다.
- Route 53 기반 origin 레코드 구성을 DuckDNS로 전환했다. Foundation은 `OriginElasticIp`를 출력하고, `sync-duckdns-local.sh`가 Secrets Manager의 `DUCKDNS_TOKEN`으로 DuckDNS A 레코드를 갱신한다.
- `workshield.duckdns.org`은 Foundation Elastic IP `43.200.136.32`로 해석되는 것을 확인했다.
- Foundation 최초 배포 중 CDK execution policy의 IAM role 권한과 Security Group description ASCII 제약으로 실패했다. `WorkShield*` role/instance profile 범위에 필요한 IAM 권한을 보완하고 실패 stack 및 빈 placeholder secret을 정리한 뒤 Foundation을 `CREATE_COMPLETE`로 배포했다.
- `vllm`, `embed`, `origin-header`, `law`, `duckdns` runtime secret은 사용자 terminal에서 등록했다. vLLM·Embedder key는 새로 생성했다.
- Service stack은 S3 auto-delete custom resource Lambda 생성 권한이 없어 실패했다. Lambda action은 `WorkShieldService-*` ARN에만 제한해 생성·조회·수정·삭제·태그·permission 연결 권한으로 보완했다.
- 재배포 중 Custom Resource가 Lambda를 호출할 때 `lambda:InvokeFunction` 누락으로 다시 rollback 됐다. 같은 `WorkShieldService-*` 범위에 `lambda:InvokeFunction`을 추가하고 실패 stack을 정리한 뒤 `WorkShieldService`를 `CREATE_COMPLETE`로 배포했다. CloudFront distribution은 `E1NGL2RMJYFTTW`, web bucket은 `workshieldservice-webbucket12880f5b-kdtscsxdlwa1`이며, origin EC2 `i-06acbf8835c342dcb`의 SSM 상태는 `Online`이다.
- `provision-duckdns-tls-local.sh`와 `just duckdns-tls-provision-local <ACME 이메일>`을 추가했다. 이 도구는 인스턴스에서 DuckDNS DNS-01 hook, origin 인증서 반영 hook, 일일 Certbot 갱신 timer를 구성한다.
- 첫 TLS provisioning 실행은 Amazon Linux의 `curl-minimal`과 전체 `curl` 패키지 충돌로 Certbot 실행 전에 실패했다. 기본 제공 `curl`·`python3`·`aws`를 재설치하지 않고 존재 여부만 확인하도록 수정해 재시도했다.
- `workshield.duckdns.org` Let’s Encrypt DNS-01 인증서를 성공적으로 발급했다. 인증서 만료일은 `2026-10-27`이며, `/opt/workshield/certificates/{fullchain.pem,privkey.pem}`은 `0600` 권한으로 배치됐다. `workshield-certbot-renew.timer`는 `enabled`·`active` 상태로 매일 갱신을 확인한다.
- EC2에 secret 없는 Compose·Nginx template·container deployment/rollback script runtime asset을 SSM으로 설치했다 (`edb42b06-ff0d-4571-8830-b48187206e4a`).
- 기존 로컬 `workshield-api:local`, `workshield-mcp:local` 이미지를 `ghcr.io/hong1008/skn30-4th-2team/{api,mcp}:dd992d0e64eb2818c9a61b85840c456cc8292325`로 게시하고 두 manifest digest를 확인했다. API는 `sha256:9abf06e94d356e6357b6aaec13707e8dde7841adc40718700e220ef32e6a969d`, MCP는 `sha256:b952e1cf689a4790d1ecf213057ea00d8ac735b644b62911bce7947e3062ae1e`이다.
- EC2 배포 전 익명 GHCR pull을 확인한 결과 두 image 모두 `401`이었다. runtime parameter는 모두 존재하지만 package가 private여서 EC2가 인증 없이 pull할 수 없다.
- 사용자 PAT는 GHCR image publish와 package metadata 조회에 성공했다. 그러나 GitHub REST Packages API에는 package visibility 변경 endpoint가 제공되지 않아 두 PATCH 요청은 `404`로 거부됐고, package visibility는 변경되지 않았다.
- 사용자가 GitHub package 설정 화면에서 API·MCP package를 public으로 전환한 뒤 Docker 익명 bearer 흐름으로 다시 확인했으며, 두 manifest 모두 인증 없이 pull 가능했다. 최초 `curl`의 `401`은 registry bearer challenge로 판명됐다.
- release `dd992d0e64eb2818c9a61b85840c456cc8292325`를 SSM deployment document로 배포했으나 `/workshield/prod/vllm/base-url`이 `__UNSET__`이라 실패했다 (`962ce567-bd62-4a1f-8422-63fe9a3ff790`). RunPod LLM/Embed state와 vLLM model parameter도 전부 `__UNSET__`이므로 실제 Pod endpoint 연결이 선행돼야 한다.
- RunPod CLI 인증과 local `RUNPOD_API_KEY` 존재를 확인한 뒤 LLM Pod를 생성했다 (`zga31ktbiwsu5j`, `RUNNING`). vLLM server는 최초 readiness 확인에서 `502`로 모델 초기화 중이었고, endpoint/model Parameter Store 기록은 readiness 완료 후 처리해야 한다.
- Embed Pod는 기본 GPU `NVIDIA RTX 2000 Ada`가 현재 RunPod 가용 목록에 없어 생성되지 않았다. `NVIDIA A40`, `NVIDIA GeForce RTX 3090`, `NVIDIA GeForce RTX 4090`, `NVIDIA RTX A5000` 등은 가용 상태다. Pod 생성 scripts는 RunPod CLI 상세 오류를 출력하도록 보완했다.
- 사용자 선택 `NVIDIA RTX A5000`으로 Embed Pod `2aa2ny8b7kyog6`를 생성해 `RUNNING`을 확인했다. 갱신된 AWS SSO 세션으로 health를 확인한 결과 인증 요청과 무인증 요청이 모두 `200`이었다. 운영 요구사항인 Bearer 인증 차단(`401`/`403`)을 충족하지 못하므로 `/workshield/prod/runpod/embed/base-url`에 endpoint를 기록하거나 container release를 재개하지 않았다. 현재 RunPod template image가 저장소의 인증 적용 `pod_server.py`와 일치하도록 갱신돼야 한다.
- 사용자가 위험을 인지하고 "기록에만 남기고 컨테이너 배포"를 명시적으로 지시했다. 따라서 Embed authentication 검증 실패를 보안 부채로 유지한 채 endpoint를 runtime Parameter Store에 연결하고 container release를 진행한다. template image 교체와 무인증 차단 재검증은 배포 후 필수 후속 작업이다.
- EC2에는 Docker가 없어 첫 container release가 실패했다. Docker Engine을 설치·기동하고 Docker Compose v2 plugin(`v5.1.2`)을 공식 Docker 배포 binary로 설치했다. Service stack bootstrap도 Amazon Linux package 충돌을 피하도록 Docker 설치와 Compose plugin 설치를 분리했다.
- 초기 Nginx digest는 Docker Hub manifest에 존재하지 않아 container를 기동하지 못했다. 공식 `nginx:stable` manifest digest `sha256:f0dab47df05ce89c0e40ae9776ef829a1596c747409469a979a0283d1d73bb13`로 `prod.env`와 runtime parameter를 갱신했다. release script는 API/MCP/Nginx 세 서비스가 실제 running 상태인지 확인하도록 보완했다.
- MCP는 healthy였으나 API의 `Host: mcp:8000` 요청이 FastMCP DNS rebinding protection에서 `421`로 거부돼 API가 재시작했다. FastMCP 생성 시 `MCP_ALLOWED_HOSTS`의 제한 allowlist를 적용하도록 수정했다. 이 수정은 새 MCP image build·versioned publish 후 재배포가 필요하다.
- RunPod endpoint를 연결한 뒤 release를 다시 시도했으나 `/workshield/prod/runtime/ghcr-owner` parameter 누락으로 실패했다 (`917bc470-6255-4bf5-b23c-b49a5c449b0d`). 누락 parameter를 보완한 다음 실행한 SSM command `7811f35f-30f9-475b-a0d7-e76fe5dc8cc2`는 release SHA를 활성화했지만, MCP의 `421` 응답으로 API가 재시작을 반복해 정상 운영 release로 판정할 수 없었다.
- 환경 변수만으로 FastMCP의 이미 생성된 transport security 설정을 바꾸는 방식은 적용되지 않았다. `mcp/src/app.py`에서 `TransportSecuritySettings`를 명시적으로 전달하도록 로컬 코드를 수정했지만, 수정 image를 새 SHA로 build·publish·재배포하기 전에 테스트를 종료했다.
- 따라서 container release 명령 자체는 실행됐고 활성 SHA parameter도 기록됐으나, API health와 end-to-end 요청이 통과한 유효한 production release는 없었다. web release와 CloudFront viewer 경로 검증도 수행하지 않았다.

주의:

- placeholder secret이 보존 정책으로 남은 상태에서 stack 생성이 실패하면 같은 이름의 secret이 재배포를 막는다. 실제 값을 아직 넣기 전인 빈 placeholder만 사용자가 명시적으로 승인한 뒤 즉시 삭제한다.
- container release는 시도했지만 API 비정상으로 완료되지 않았고, web release는 실행하지 않았다. origin TLS 인증서와 자동 갱신은 구성 완료됐다.

## 테스트 종료 시점의 미완료·실패 항목

1. 현재 로컬의 인프라 변경을 검토·commit·push하여 GitHub Actions가 동일한 deployment workflow와 script를 사용할 수 있게 한다. 현재 local `main`은 remote보다 앞서 있으며, 추가 변경도 아직 working tree에 있다.
2. Embed RunPod template image를 인증 적용 `pod_server.py` 버전으로 갱신하지 못했다. 마지막 확인에서 인증 요청과 무인증 요청이 모두 `200`이어서 Bearer 인증 요구사항을 충족하지 못했다.
3. FastMCP Host allowlist 수정이 포함된 새 versioned MCP image를 build·publish하지 못했다. 그 결과 MCP 자체 health는 통과했지만 API→MCP 요청은 `421`이었고 API가 재시작을 반복했다.
4. 정상 container release, web release, CloudFront viewer URL, origin health, SSE end-to-end 검증을 완료하지 못했다.
5. GitHub Actions를 통한 동일 절차 재현, rollback, destroy workflow 검증을 수행하지 못했다.

## 2026-07-29 테스트 종료 및 리소스 폐기

- 사용자가 테스트 종료를 결정했다. 지금까지의 누락·실패를 위에 기록하고, 이후 비용이 발생하는 WorkShield 리소스만 폐기한다.
- 폐기 대상은 RunPod LLM·Embed Pod, `WorkShieldService` stack의 EC2·CloudFront·S3 등 서비스 리소스, `WorkShieldFoundation` stack의 Elastic IP·EBS·VPC·CloudWatch Log Group 등 foundation 리소스, 그리고 stack 삭제 뒤 보존되는 Secrets Manager secret이다.
- Secrets Manager secret은 즉시 영구 삭제하지 않고 7일 복구 유예로 삭제 예약한다.
- GitHub OIDC provider·deploy role, GitHub Environments·GHCR package, DuckDNS record, CDK bootstrap처럼 연결 기반 또는 공유 성격의 리소스는 이번 폐기 범위에서 제외한다. DuckDNS record는 Elastic IP 반환 후 더 이상 유효한 origin을 가리키지 않으므로 재사용 전 반드시 갱신해야 한다.
- RunPod LLM Pod `zga31ktbiwsu5j`와 Embed Pod `2aa2ny8b7kyog6`에 멱등 삭제 명령을 실행했다. 두 명령 모두 이미 존재하지 않는 Pod로 응답했으며, 최종 `runpodctl pod list` 결과가 빈 목록임을 확인했다.
- `WorkShieldService`를 먼저 삭제하고 완료를 기다린 뒤 `WorkShieldFoundation`을 삭제했다. 두 stack 모두 더 이상 조회되지 않는다.
- 삭제 후 실행·정지 상태 EC2는 없고, Elastic IP `eipalloc-0f14dde9d400e796f`, CloudFront distribution `E1NGL2RMJYFTTW`, web bucket `workshieldservice-webbucket12880f5b-kdtscsxdlwa1`, WorkShield EBS volume은 모두 `NotFound` 또는 빈 목록으로 확인됐다. `/workshield/prod` SSM parameter와 WorkShield NAT Gateway도 남지 않았다.
- Resource Groups Tagging API에는 삭제된 EC2 `i-06acbf8835c342dcb`와 EBS volume의 과거 tag index가 남아 있었지만, 직접 조회 결과 EC2는 `terminated`, 두 EBS volume은 `NotFound`여서 과금 가능한 실행·저장 리소스가 아니다.
- stack 보존 정책으로 남은 Secrets Manager secret 중 테스트용 `/workshield/prod/vllm`, `/workshield/prod/embed`, `/workshield/prod/origin-header`는 7일 복구 유예로 삭제 예약했다. 이어서 사용자의 명시적 승인에 따라 외부 서비스 자격정보인 `/workshield/prod/law`, `/workshield/prod/duckdns`도 같은 방식으로 삭제 예약했다. 다섯 secret의 예정 삭제일은 `2026-08-05`다.
- 공유 CDK bootstrap은 유지했다. ECR bootstrap repository는 image `0`개이고, S3 bootstrap bucket에는 CDK asset `59,401` bytes가 남아 있어 소액 저장 비용이 발생할 수 있다.
- GitHub OIDC provider·deploy role, GitHub Environments·GHCR public package와 DuckDNS record는 그대로 남겼다. DuckDNS는 반환된 `43.200.136.32`를 계속 가리킬 수 있으므로 현재 운영 endpoint로 사용하면 안 된다.

DuckDNS는 Route 53 hosted zone을 사용하지 않으며, `workshield.duckdns.org`은 CloudFront의 viewer custom domain이 아니라 CloudFront→EC2 origin TLS domain이다.

## 공식 참고

- [AWS CDK prerequisites](https://docs.aws.amazon.com/cdk/v2/guide/prerequisites.html)
- [AWS CDK bootstrap](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-bootstrap.html)
- [AWS CLI v2 설치](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [GitHub Container registry 인증](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [GitHub package visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)
