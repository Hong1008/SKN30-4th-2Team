# AWS 배포 아키텍처

이 문서는 AWS 리소스와 네트워크, CDK 관리 경계, EC2의 컨테이너 구성을
정의한다. GitHub Actions의 세부 job은 [CI/CD](ci-cd.md), 키와 인증서는
[비밀 관리](secrets-management.md), 실제 실행 순서는
[운영 Runbook](operations-runbook.md)에서 다룬다.

## 전체 구성

```text
사용자 브라우저
       │ HTTPS
       ▼
CloudFront (기본 cloudfront.net 도메인)
       ├─ /*             → 비공개 S3 Web bucket(OAC)
       ├─ /api/*         → EC2 origin HTTPS
       └─ /health/*      → EC2 origin HTTPS
                              │
                              ▼
                  t3.small EC2 / Docker Compose
                  ├─ Nginx :443
                  ├─ API :8000
                  └─ MCP :8000/mcp
                         ├─ RunPod Embedder·Reranker
                         └─ RunPod vLLM

GitHub Actions
       ├─ GITHUB_TOKEN → ghcr.io 이미지 push
       ├─ RUNPOD_API_KEY → RunPod Pod 생성·삭제
       └─ GitHub OIDC  → AWS IAM role
                              ├─ CDK/CloudFormation
                              ├─ S3·CloudFront 배포
                              └─ SSM Run Command → EC2 Compose 갱신
```

## CloudFront와 S3

### 정적 웹

- S3 public access를 모두 차단한다.
- CloudFront Origin Access Control로만 S3 object를 읽는다.
- 기본 behavior `/*`를 S3 origin에 연결한다.
- Vite build 결과인 `web/dist/`만 배포한다.
- S3 versioning 또는 release별 artifact를 유지해 웹 롤백을 가능하게 한다.

React Router 새로고침은 기본 S3 behavior에만 연결한 CloudFront Function으로
처리한다. 확장자가 없는 화면 경로만 `/index.html`로 rewrite한다.

배포 전체의 403·404 custom error를 `/index.html` 200으로 바꾸면 안 된다.
API가 소유권 은폐를 위해 반환하는 404까지 HTML 200으로 바뀔 수 있다.

### API behavior

`/api/*`, `/health/*` behavior는 다음 원칙을 적용한다.

- cache policy: `CachingDisabled`
- 모든 query string과 Cookie를 origin으로 전달
- `GET`, `HEAD`, `OPTIONS`, `PUT`, `POST`, `PATCH`, `DELETE` 허용
- `Idempotency-Key`, `Last-Event-ID`, `X-Request-ID`, `Content-Type` 전달
- viewer HTTP 요청은 HTTPS로 redirect
- API 응답에 `Cache-Control: no-store`

SSE는 Nginx buffering과 proxy cache를 사용하지 않는다. CloudFront origin
response timeout보다 짧은 주기의 heartbeat를 유지한다.

## EC2 origin 보안

### 네트워크

- EC2에는 고정 Elastic IP를 연결한다.
- DuckDNS origin 이름(`workshield.duckdns.org`)을 Elastic IP로 연결한다.
- security group의 443 inbound는 AWS managed prefix list
  `com.amazonaws.global.cloudfront.origin-facing`에서만 허용한다.
- SSH 22 inbound는 열지 않는다.
- API와 MCP 컨테이너 포트는 host 외부에 publish하지 않는다.
- 운영 접속은 SSM Session Manager를 사용한다.

CloudFront prefix list만으로는 특정 distribution 하나를 식별할 수 없다.
CloudFront origin 설정에 충분히 긴 무작위 header를 추가하고 Nginx가 같은
값을 검증해야 한다. 둘 중 하나만 적용하지 않는다.

### TLS

viewer는 CloudFront 기본 인증서를 사용한다. CloudFront와 EC2 사이에는
origin domain과 일치하는 공인 인증서를 설치하고 origin protocol policy를
`HTTPS only`로 설정한다.

ALB를 사용하지 않으므로 ACM public certificate를 Nginx에 직접 연결할 수
없다. DuckDNS TXT API를 이용한 DNS-01으로 인증서를 발급하고 다음 경로를
암호화된 EBS에 보관한다.

```text
/opt/workshield/certificates/
```

인증서 자동 갱신 후 Nginx reload가 실행되어야 한다. 인증서가 준비되기 전에
CloudFront origin을 `HTTPS only`로 전환하지 않는다.

## EC2와 Docker Compose

EC2 기준 사양은 `t3.small`이며 API와 MCP는 각각 단일 프로세스로 실행한다.

```text
/opt/workshield/
├─ compose.prod.yaml
├─ releases/
├─ secrets/
│  ├─ api.env
│  └─ mcp.env
└─ data/
   ├─ api/
   │  ├─ workshield.db
   │  └─ 99_uploads/
   └─ certificates/
```

Compose 서비스는 다음과 같이 구성한다.

| 서비스 | 이미지 | 외부 공개 | 역할 |
| --- | --- | --- | --- |
| `nginx` | 고정된 공식 Nginx image digest | 443 | CloudFront origin, TLS, SSE proxy |
| `api` | `ghcr.io/<owner-lower>/skn30-4th-2team/api:<git-sha>` | 없음 | FastAPI, SQLite, 세션·검토 |
| `mcp` | `ghcr.io/<owner-lower>/skn30-4th-2team/mcp:<git-sha>` | 없음 | 문서 파싱, 검색·재정렬 연계 |

API의 MCP 주소는 Docker service DNS를 사용한다.

```dotenv
WORKSHIELD_MCP_TRANSPORT=streamable_http
WORKSHIELD_MCP_URL=http://mcp:8000/mcp
```

`depends_on`만으로 준비 완료를 판단하지 않는다. MCP health check가 성공한
뒤 API를 시작하거나, API가 MCP 준비 실패 시 ready 상태가 되지 않도록 한다.

## 데이터 볼륨

사용자 데이터와 MCP 정적 corpus는 백업 정책이 다르므로 분리한다.

| 볼륨 | 내용 | 암호화 | snapshot |
| --- | --- | --- | --- |
| MCP corpus | Chroma, 표준계약서 SQLite, 정적 corpus | EBS 암호화 | 허용 |
| 임시 사용자 데이터 | API SQLite, 업로드, 결과·대화 | EBS 암호화 | 제외 |

임시 사용자 데이터 볼륨은 EC2 종료 시 삭제되도록 설정하고 자동 snapshot이나
AMI에 포함하지 않는다. 정상 가동 중에는 애플리케이션이 만료 후 최대 60초
이내 삭제하며, 비정상 종료·정지 후에는 다음 기동 시 정리한다.

## GHCR

애플리케이션 이미지 레지스트리로 AWS ECR을 사용하지 않는다. API와 MCP
이미지는 GitHub Container Registry에 저장한다.

```text
ghcr.io/<owner-lower>/skn30-4th-2team/api:<git-sha>
ghcr.io/<owner-lower>/skn30-4th-2team/mcp:<git-sha>
ghcr.io/<owner-lower>/skn30-4th-2team/embed-rerank:<git-sha>
```

이미지에 비밀을 넣지 않는다. 현재 소스와 MCP corpus가 공개 가능한
artifact라는 전제에서는 package visibility를 `public`으로 설정해 EC2가
자격증명 없이 pull하도록 하는 구성을 권장한다. GHCR package를 public으로
바꾸면 다시 private으로 되돌릴 수 없으므로 최초 공개 전에 image layer와
포함 데이터를 확인한다.

private package가 필요해지면 EC2에는 `read:packages`만 가진 별도
Personal Access Token(classic)을 사용한다. GitHub Actions의 `GITHUB_TOKEN`은
EC2에서 사용할 수 없다.

GitHub 문서상 public package는 무료이며 Container registry의 image storage와
bandwidth도 현재 무료다. 정책 변경 가능성이 있으므로 GitHub billing 알림과
package 보존 정책은 유지한다.

## CDK 관리 경계

AWS CDK v2 Python을 인프라 원본으로 사용한다.

CDK v2의 기본 bootstrap stack은 Docker asset용 ECR repository도 생성한다.
이 repository는 CDK 도구의 staging 자원이며 WorkShield API·MCP image
registry로 사용하지 않는다. CDK 코드에서 `DockerImageAsset`을 사용하지 않아
애플리케이션 image가 이 repository에 게시되지 않도록 한다. 기본 bootstrap의
빈 ECR resource 자체도 허용하지 않는 정책이라면 custom bootstrap template
또는 직접 CloudFormation 배포로 전환해야 한다.

### bootstrap 영역

GitHub Actions가 AWS role을 맡기 전 한 번만 관리자가 실행한다.

- GitHub OIDC identity provider
- GitHub production deploy role과 trust policy
- CloudFormation execution role
- CDK bootstrap resources

OIDC와 최초 role 생성은 순환 의존성이 있으므로
`deploy/aws/bootstrap/github-oidc-role.yaml`과 AWS CLI wrapper로 관리한다.

### foundation stack

- IAM instance role
- EC2 security group
- EBS 볼륨과 암호화
- Elastic IP
- Route 53 origin record
- Secrets Manager·Parameter Store 경로
- CloudWatch log group과 기본 경보

### service stack

- EC2 launch template 또는 단일 instance
- S3 web bucket
- CloudFront OAC·distribution·behaviors
- CloudFront Function
- origin custom header 연결
- SSM document

CDK stack은 secret 값을 CloudFormation output, tag, context 또는 로그에
노출하지 않는다.

## IAM 역할

역할은 다음과 같이 분리한다.

| 역할 | 주체 | 최소 권한 |
| --- | --- | --- |
| GitHub deploy role | GitHub OIDC | CDK deploy, S3 web, CloudFront invalidation, SSM command |
| CloudFormation execution role | CloudFormation | 선언된 WorkShield AWS 리소스 생성·변경 |
| EC2 instance role | EC2 | SSM, CloudWatch, 지정 secret·parameter 읽기 |

GitHub OIDC trust는 실제 배포 저장소와 `production` Environment로 제한한다.
저장소나 Environment 전체 wildcard는 사용하지 않는다.

RunPod는 CDK 관리 대상이 아니다. 기존 Python script와 `runpodctl`을 GitHub
Actions가 호출하며, 생성된 Pod ID와 base URL은 Parameter Store에 저장한다.
수명주기와 삭제 경계는 [RunPod 자동화](runpod-automation.md)를 따른다.

## 관련 공식 문서

- [AWS CDK 애플리케이션 배포](https://docs.aws.amazon.com/cdk/v2/guide/deploy.html)
- [AWS CDK bootstrap이 생성하는 자원](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-bootstrap.html)
- [CloudFront custom origin 설정](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/DownloadDistValuesOrigin.html)
- [CloudFront custom origin 접근 제한](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-overview.html)
- [AWS Systems Manager Run Command](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command.html)
- [GitHub Packages billing](https://docs.github.com/en/billing/concepts/product-billing/github-packages)
