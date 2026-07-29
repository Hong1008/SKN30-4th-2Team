# 배포 비밀 관리

이 문서는 배포와 runtime에 필요한 credential의 발급, 저장, 주입, 회전과
폐기를 정의한다. 실제 명령 실행 순서는 [운영 Runbook](operations-runbook.md)을
따른다.

## 원칙

- 장기 AWS access key를 GitHub에 저장하지 않는다.
- GitHub Actions의 AWS 접근에는 OIDC 단기 credential을 사용한다.
- runtime secret은 AWS Secrets Manager에 저장한다.
- 비밀이 아닌 runtime 설정은 SSM Parameter Store에 저장한다.
- secret 값은 Git, CDK context, CloudFormation output, GitHub Actions log,
  SSM Run Command parameter에 포함하지 않는다.
- EC2는 instance role로 자신에게 필요한 secret만 읽는다.
- 발급자, 저장 위치, 회전일과 폐기 결과를 운영 기록으로 남긴다.

## 분류

### GitHub Environment Variables

다음은 비밀이 아니라 배포 대상 식별자다.

```text
AWS_DEPLOY_ROLE_ARN
CDK_APP_NAME
AWS_REGION
```

`production` Environment에 저장해 배포 대상별로 분리한다.

container release Command document 이름은 CDK app name을 기준으로 고정한다.
기본 production 구성의 이름은 `workshield-prod-deploy`이며, workflow는 SSM command에
release SHA만 전달한다.
AWS account ID, region, origin domain과 hosted zone ID는 비밀이 아니며
`deploy/aws/config/prod.json`에서 관리한다. `GHCR_OWNER`는
`deploy-production.yml`의 수동 입력값으로 받아 소문자로 정규화한다.

### GitHub Environment Secrets

```text
RUNPOD_API_KEY
```

GitHub runner가 AWS보다 먼저 RunPod Pod를 생성·조회·삭제해야 하므로
`RUNPOD_API_KEY`는 `production`과 `production-destroy` Environment에서
사용한다. GitHub Actions는 이를 `RUNPOD_API_KEY` 환경 변수로 `runpodctl`에
전달하며 `runpodctl config` 파일로 저장하지 않는다.

두 Environment에 같은 장기 key를 복제하기보다 organization 또는 repository
secret 하나를 environment 접근 규칙으로 통제할 수도 있다. 어느 방식을
사용하든 값이 승인 전 job에 노출되지 않게 한다.

### AWS Secrets Manager

권장 경로:

```text
/workshield/prod/vllm
/workshield/prod/embed
/workshield/prod/origin-header
/workshield/prod/ghcr-read          # private package일 때만
/workshield/prod/huggingface        # 필요할 때만
```

secret JSON 예:

```json
{
  "VLLM_API_KEY": "workflow가 생성",
  "HUGGING_FACE_TOKEN": "필요할 때만 등록"
}
```

`/workshield/prod/embed` secret은 MCP runtime 환경 변수와 같은 이름을 사용한다.

```json
{
  "RUNPOD_EMBED_API_KEY": "workflow가 생성"
}
```

### SSM Parameter Store

비밀이 아닌 설정:

```text
/workshield/prod/release/active-sha
/workshield/prod/vllm/base-url
/workshield/prod/vllm/model
/workshield/prod/runpod/llm/pod-id
/workshield/prod/runpod/embed/pod-id
/workshield/prod/runpod/embed/base-url
/workshield/prod/api/session-ttl-seconds
/workshield/prod/api/max-upload-size-bytes
```

## 비밀 목록

| 이름 | 발급 | 저장 | 소비자 |
| --- | --- | --- | --- |
| AWS deploy credential | GitHub OIDC로 매 job 자동 발급 | 저장하지 않음 | GitHub Actions |
| `RUNPOD_API_KEY` | RunPod 계정에서 발급 | GitHub Environment Secret | GitHub Actions의 Pod 관리 |
| `VLLM_API_KEY` | 무작위 32-byte 값 생성 | Secrets Manager·vLLM Pod | API·vLLM |
| Embedder API key | 무작위 32-byte 값 생성 | Secrets Manager·Embedder Pod | MCP·Embedder |
| origin header | 무작위 32-byte 이상 값 생성 | Secrets Manager | CloudFront·Nginx |
| `GHCR_READ_TOKEN` | PAT classic, `read:packages`만 | Secrets Manager | EC2, private package일 때만 |
| `HUGGING_FACE_TOKEN` | Hugging Face 계정에서 발급 | Secrets Manager | 모델 pull이 필요할 때만 |
| TLS private key | DNS-01 인증 과정에서 생성 | 암호화 EBS root 전용 경로 | Nginx |
| session access token | API가 요청별 생성 | 원문 미저장, DB에는 hash | 브라우저·API |

## 발급과 설정

### AWS GitHub OIDC

OIDC에는 공유 비밀이 없다.

1. AWS IAM에 `token.actions.githubusercontent.com` provider를 등록한다.
2. audience를 `sts.amazonaws.com`으로 제한한다.
3. deploy role trust를 실제 repository와 `production` Environment로 제한한다.
4. GitHub `production` Environment에는 role ARN만 Variable로 저장한다.

trust policy에 repository 또는 subject 전체 wildcard를 사용하지 않는다.

### VLLM API key

관리자 환경에서 생성한다.

```bash
openssl rand -hex 32
```

같은 값을 vLLM Pod의 server API key와 AWS Secrets Manager의
`VLLM_API_KEY`에 설정한다. 자동 배포에서는 workflow가 생성하되 stdout,
GitHub Actions output, shell history에 값을 남기지 않는다.

회전 순서:

1. 새 key를 생성한다.
2. vLLM endpoint가 새 key를 받도록 갱신한다.
3. Secrets Manager version을 갱신한다.
4. API container를 재시작한다.
5. 실제 요청 성공을 확인한다.
6. 이전 key를 폐기한다.

### RunPod API key

RunPod 계정에서 운영 전용 key를 발급한다. 개인 개발 key와 운영 key를
공유하지 않는다.

Pod 생성·조회·삭제에 필요한 최소 범위를 선택하고 실제
create/get/list/delete가 되는지 bootstrap 전에 확인한다. RunPod Console에서
Pod 단위 제한을 제공하지 않는 경우에는 Pod 관리가 가능한 운영 전용 key를
별도로 만들고 개인 개발 key와 분리한다. 두 runtime 모두 Pod base URL로 직접
호출하므로 EC2의 API·MCP container에는 RunPod 관리 key를 주입하지 않는다.

RunPod는 API key를 다시 표시하지 않으므로 발급 직후 password manager와
GitHub Environment Secret에 안전하게 등록한다.

### Embedder API key

RunPod Pod HTTP proxy는 공개 인터넷에서 접근할 수 있으므로 Embedder·Reranker
worker가 별도 API key를 검증하도록 구현한다. workflow가 32-byte 이상
무작위 값을 생성해 Pod와 `/workshield/prod/embed` secret에 함께 설정한다.
MCP client는 인증 header를 보내며 무인증 요청 실패를 readiness 조건으로
검사한다.

### Origin header

```bash
openssl rand -hex 32
```

CloudFront가 origin 요청에 추가하고 Nginx가 일치 여부를 확인한다.

회전은 일시적인 origin 차단을 피하도록 다음 순서를 사용한다.

1. Nginx가 이전 값과 새 값을 잠시 모두 허용한다.
2. CloudFront를 새 값으로 갱신한다.
3. 배포 완료와 API 접근을 확인한다.
4. Nginx에서 이전 값을 제거한다.
5. Secrets Manager에서 이전 version을 폐기한다.

secret 값을 CDK output이나 CloudFront 설명 tag에 넣지 않는다.

### GHCR

#### Public package

권장 구성이다. EC2는 anonymous pull을 사용하므로 GHCR secret이 없다.
GitHub Actions push는 job별 `GITHUB_TOKEN`과 `packages: write`를 사용한다.
public 전환 후에는 private으로 되돌릴 수 없으므로 image 공개 가능 여부를
먼저 승인한다.

#### Private package

package를 처음부터 private으로 운영할 때만 별도 machine user 또는 운영 계정에서 PAT
classic을 발급한다.

- scope: `read:packages`
- `write:packages`, `delete:packages`, `repo`는 불필요하면 부여하지 않음
- Secrets Manager의 `/workshield/prod/ghcr-read`에 저장
- EC2에서 `docker login ghcr.io --password-stdin`으로만 사용

개인 개발 PAT를 EC2에 설치하지 않는다.

### TLS 인증서

origin domain의 공인 인증서는 DNS-01로 발급한다. Route 53을 사용할 경우
EC2 instance role에 해당 hosted zone의 DNS challenge record 변경 권한만
부여한다.

private key:

- `/opt/workshield/certificates`의 전용 인증서 볼륨에 저장
- owner `root`
- 암호화된 EBS 사용
- image, Git, S3 web artifact, snapshot에 포함 금지
- 자동 갱신 후 Nginx reload

인증서와 key 본문을 Secrets Manager에 복제하지 않는 것을 기본으로 한다.

## EC2 주입

EC2는 배포 시 instance role로 secret을 읽고 root 전용 파일을 만든다.

```text
/opt/workshield/secrets/api.env   0600 root:root
/opt/workshield/secrets/mcp.env   0600 root:root
```

Compose는 `env_file`로 읽는다. 파일이 있는 볼륨은 EBS 암호화를 사용하고
snapshot 대상에서 제외한다.

SSM command에는 secret 값이 아니라 secret identifier만 전달한다. command가
AWS API로 값을 읽고 파일로 바로 기록하며 stdout에 출력하지 않는다.

## 로그와 오류 처리

다음을 금지한다.

- `set -x`
- `.env` 또는 secret JSON `cat`
- `aws secretsmanager get-secret-value` 결과를 terminal에 출력
- secret이 포함된 `docker inspect` 결과를 CI artifact로 저장
- exception에 전체 environment 포함
- GitHub Actions output에 secret 등록

GitHub masking은 보조 수단일 뿐이며 값을 출력해도 된다는 의미가 아니다.

## 회전 주기

| 비밀 | 권장 시점 |
| --- | --- |
| OIDC credential | job마다 자동 만료 |
| VLLM API key | 유출 의심, 담당자 변경, 정기 운영 점검 |
| RunPod API key | 유출 의심, 담당자 변경, 공급자 정책에 따른 주기 |
| origin header | 유출 의심 또는 정기 운영 점검 |
| Embedder API key | Pod 교체, 유출 의심, 담당자 변경 |
| GHCR PAT | private package 사용 중 유출 의심·담당자 변경·만료 전 |
| TLS 인증서 | 자동 갱신, 만료 경보 유지 |

회전은 새 값 검증 후 이전 값을 폐기하는 순서로 수행한다. 단일 값 덮어쓰기로
서비스를 먼저 끊지 않는다.

## 관련 공식 문서

- [GitHub OIDC 개요](https://docs.github.com/en/actions/concepts/security/openid-connect)
- [AWS GitHub OIDC provider 구성](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp-oidc.html)
- [GitHub Container registry 인증](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [GitHub Environment secret과 승인](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [RunPod API key 관리](https://docs.runpod.io/get-started/api-keys)
- [RunPod Pod 환경 변수와 secret](https://docs.runpod.io/pods/templates/environment-variables)
- [SSM Run Command의 평문 비밀 주의사항](https://docs.aws.amazon.com/systems-manager/latest/userguide/running-commands.html)
