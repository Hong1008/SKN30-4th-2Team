# GitHub Actions CI/CD

이 문서는 GitHub Actions workflow와 GHCR image lifecycle, AWS 배포·롤백
흐름을 정의한다. AWS 리소스는 [AWS 배포 아키텍처](aws-deployment-architecture.md),
credential은 [비밀 관리](secrets-management.md)에서 다룬다.

## 원칙

- GitHub Actions를 CI/CD의 단일 오케스트레이터로 사용한다.
- workflow는 `deploy/aws/scripts/`의 명령을 호출하고 로직을 중복하지 않는다.
- CI job은 AWS 권한을 갖지 않는다.
- AWS 인증은 GitHub OIDC 단기 credential만 사용한다.
- GitHub 장기 AWS access key를 만들지 않는다.
- image tag는 commit SHA를 기준으로 하고 `latest`를 배포 기준으로 쓰지 않는다.
- 운영 배포는 한 번에 하나만 실행한다.
- AWS와 RunPod의 모든 변경 workflow는 `workflow_dispatch`로만 실행한다.
- RunPod 생성·자동 바인딩과 삭제는
  [RunPod 자동화](runpod-automation.md)의 멱등 계약을 따른다.

## Workflow 구성

### `.github/workflows/ci.yml`

trigger:

- `pull_request`
- `main` 대상 push
- 필요 시 `workflow_dispatch`

job:

1. 저장소와 MCP submodule checkout
2. API dependency 설치, pytest, ruff
3. MCP dependency 설치와 test
4. Web dependency 설치, typecheck, build
5. API·MCP container build
6. Docker Compose config 확인
7. CDK synth

MCP는 Git submodule이므로 checkout은 다음 설정을 사용한다.

```yaml
- uses: actions/checkout@<commit-sha>
  with:
    submodules: recursive
```

PR CI의 `GITHUB_TOKEN`에는 최소한의 `contents: read`만 부여한다.

### `.github/workflows/deploy-production.yml`

trigger:

- `workflow_dispatch`만 허용

`main` push로 운영 배포를 자동 실행하지 않는다. workflow input으로
`ghcr_owner`를 받고 repository 이름과 package suffix는 고정한다.

운영 job은 GitHub `production` Environment를 사용한다.

```yaml
permissions:
  contents: read
  packages: write
  id-token: write

concurrency:
  group: workshield-production
  cancel-in-progress: false
```

production Environment에는 다음 보호 규칙을 적용한다.

- 배포 branch를 `main`으로 제한
- required reviewer는 선택 사항
- 관리자 bypass 비활성화 여부 결정

`Hong1008` 한 명이 workflow 실행자이자 reviewer라면 `prevent self-review`를
활성화할 수 없다. 활성화하면 자신이 시작한 배포를 자신이 승인하지 못해
workflow가 중단된다. 수동 실행 자체가 이미 한 번의 명시적 확인이므로 정상
배포에는 required reviewer를 두지 않는 구성을 우선 권장한다.

전체 폐기는 별도 `production-destroy` Environment에서 `Hong1008`을 required
reviewer로 설정하고 self-review를 허용한다. 향후 두 번째 운영자가 생기면
self-review 방지를 활성화한다.

### `.github/workflows/rollback-production.yml`

- `workflow_dispatch`만 허용
- production Environment 승인 적용
- 롤백할 git SHA를 필수 입력으로 받음
- 해당 SHA의 API·MCP image 존재 여부를 먼저 확인
- container rollback 뒤 health check
- web artifact도 같은 release로 되돌림

롤백 workflow는 DB schema를 되돌리지 않는다. destructive migration이
필요한 배포는 별도의 변경·복구 계획 없이는 진행하지 않는다.

### `.github/workflows/destroy-production.yml`

- `workflow_dispatch`만 허용
- `production-destroy` Environment 승인 적용
- `DESTROY workshield-prod` 같은 정확한 확인 문자열을 필수 입력으로 받음
- RunPod와 AWS의 저장된 resource ID를 먼저 조회
- RunPod 비용 자원을 우선 삭제한 뒤 AWS stack을 역순 삭제
- hosted zone, 도메인 등록, 공유 OIDC·CDK bootstrap은 기본 보존
- 삭제 성공·실패·잔존 자원을 job summary에 기록

모든 변경 workflow는 같은 concurrency group을 사용한다.

## GHCR 이미지

### 이름과 tag

```text
ghcr.io/<owner-lower>/skn30-4th-2team/api:<full-git-sha>
ghcr.io/<owner-lower>/skn30-4th-2team/mcp:<full-git-sha>
ghcr.io/<owner-lower>/skn30-4th-2team/embed-rerank:<full-git-sha>
```

workflow 입력은 owner만 받는다. Docker image reference의 namespace와
repository를 소문자로 정규화하고, repository/package 이름은 workflow에서
고정한다.

편의를 위한 `main` tag는 추가할 수 있지만 Compose와 rollback은 반드시 SHA
또는 digest를 사용한다.

image에는 다음 OCI label을 넣는다.

```text
org.opencontainers.image.source=https://github.com/<owner>/<repository>
org.opencontainers.image.revision=<full-git-sha>
org.opencontainers.image.created=<UTC timestamp>
```

package가 배포 repository에 연결되어야 workflow의 `GITHUB_TOKEN` 권한이
올바르게 상속된다.

### GitHub Actions에서 push

GHCR push job은 다음 권한을 사용한다.

```yaml
permissions:
  contents: read
  packages: write
```

login credential:

```text
registry: ghcr.io
username: ${{ github.actor }}
password: ${{ secrets.GITHUB_TOKEN }}
```

별도 PAT를 GitHub Actions push용으로 만들지 않는다.

### package visibility

현재 artifact에 비공개 데이터나 key가 포함되지 않는다는 전제로 public
package 사용을 확정했다.

- EC2의 anonymous pull 가능
- GHCR pull token을 EC2에 저장할 필요 없음
- GitHub 문서상 public package와 Container registry 사용은 현재 무료

첫 package publish 직후 visibility와 repository 연결 상태를 확인한다.
public 전환은 되돌릴 수 없으므로 image에 비공개 corpus, credential, 내부
설정이 없는지 먼저 확인한다.
private package를 선택하면 [비밀 관리](secrets-management.md)의
`GHCR_READ_TOKEN` 절차를 따른다.

### 보존 정책

- 최근 성공 release와 롤백 대상 release를 보존한다.
- 운영 중인 digest는 삭제하지 않는다.
- 실패·미배포 image는 일정 기간 후 정리한다.
- package 삭제 workflow에는 별도 승인과 최소 권한을 적용한다.
- GHCR 비용 정책 변경 알림을 확인한다.

## 운영 배포 순서

build와 test는 병렬화할 수 있지만 release 적용 순서는 고정한다.

```text
수동 workflow 실행
  ↓
입력·Environment·현재 상태 검증
  ↓
API·MCP·Embedder image build
  ↓
GHCR에 SHA tag push
  ↓
GitHub OIDC로 AWS role assume
  ↓
AWS foundation과 설정 namespace 수렴
  ↓
RunPod Embedder·vLLM Pod 생성 또는 정상 Pod 재사용
  ↓
Pod readiness·인증 확인 및 URL·model ID 자동 저장
  ↓
CDK service deploy
  ↓
SSM Run Command로 EC2 Compose 갱신
  ↓
API live/ready 확인
  ↓
web/dist를 release artifact와 S3 site에 배포
  ↓
CloudFront invalidation
  ↓
배포 release SHA 기록
```

프론트엔드를 API보다 먼저 활성화하지 않는다. 새 웹이 아직 배포되지 않은 API
계약을 호출하는 상황을 피하기 위해 container health 확인 후 web을 배포한다.
정상 재배포는 RunPod Pod를 매번 새로 만들지 않는다. 명시적 교체 input이
있을 때만 새 Pod를 검증한 뒤 이전 Pod를 삭제한다.

## EC2 배포 명령

GitHub runner가 SSH로 접속하지 않는다. deploy role이 SSM Run Command를
보내고 EC2 instance role이 다음 작업을 수행한다.

1. 지정된 SHA의 image manifest 확인
2. 필요한 경우 GHCR login
3. `compose.prod.yaml`과 release SHA 적용
4. `docker compose pull`
5. `docker compose up -d --remove-orphans`
6. health check
7. 성공 시 활성 release SHA를 Parameter Store에 기록
8. 실패 시 이전 SHA로 복구

Run Command parameter에 secret 값을 포함하지 않는다. EC2가 자신의 instance
role로 Secrets Manager 값을 읽는다.

## AWS OIDC

GitHub workflow는 `id-token: write` 권한으로 OIDC token을 발급받고 AWS STS의
단기 credential로 교환한다.

IAM trust policy는 다음 값을 함께 제한한다.

- audience: `sts.amazonaws.com`
- repository: 실제 배포 repository
- subject: `production` Environment

Environment를 사용하는 경우 subject 형식은 다음 원칙을 따른다.

```text
repo:<owner>/<repository>:environment:production
```

branch 제한은 GitHub production Environment의 deployment branch policy에도
적용한다.

## Action 공급망

- 공식 또는 검토한 Action만 사용한다.
- release tag 대신 commit SHA pin을 기본으로 한다.
- Dependabot으로 Action version 변경을 검토한다.
- fork PR에서는 package push와 AWS credential 발급을 수행하지 않는다.
- workflow에서 `.env`, token, CDK secret parameter를 출력하지 않는다.
- shell debug의 `set -x`를 사용하지 않는다.

## 실패 처리

| 실패 지점 | 처리 |
| --- | --- |
| test/build 실패 | image push·AWS 배포 없음 |
| GHCR push 실패 | AWS 배포 없음 |
| RunPod 생성 실패 | 해당 실행에서 만든 Pod 삭제, 기존 parameter 유지 |
| RunPod readiness 실패 | AWS runtime 전환 중단, 새 Pod 삭제 |
| CDK deploy 실패 | 현재 release 유지 |
| SSM command 실패 | 이전 container 유지 또는 자동 복구 |
| API health 실패 | web 배포 중단, 이전 SHA 복구 |
| web 배포 실패 | 정상 API는 유지, 이전 web release 복구 |
| CloudFront invalidation 실패 | 재시도; object version으로 상태 확인 |

## 관련 공식 문서

- [GitHub Actions로 container image 게시](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)
- [GitHub Actions에서 package 게시·설치](https://docs.github.com/en/packages/managing-github-packages-using-github-actions-workflows/publishing-and-installing-a-package-with-github-actions)
- [GitHub deployment와 Environment](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [GitHub deployment 승인](https://docs.github.com/en/actions/how-tos/managing-workflow-runs-and-deployments/managing-deployments/reviewing-deployments)
- [GitHub OIDC](https://docs.github.com/en/actions/concepts/security/openid-connect)
- [AWS의 GitHub OIDC role 제한](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp-oidc.html)
- [RunPod Pod 자동화](https://docs.runpod.io/runpodctl/reference/runpodctl-pod)
