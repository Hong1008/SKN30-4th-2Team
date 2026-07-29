# AWS 배포 운영 Runbook

이 문서는 운영자가 최초 환경을 준비하고 정상 배포·롤백·비밀 회전을 수행하는
순서를 정의한다. 리소스 정의는 [AWS 배포 아키텍처](aws-deployment-architecture.md),
workflow 계약은 [CI/CD](ci-cd.md), 값별 보안 규칙은
[비밀 관리](secrets-management.md)를 우선한다.

실제 script가 추가되면 이 문서의 명령은 `deploy/aws/scripts/`의 entrypoint와
일치시켜야 한다.

## 1. 최초 준비

### 1.1 배포 주체 확정

다음을 먼저 결정한다.

- GitHub Actions를 실행할 실제 repository
- GHCR package owner
- AWS account와 region
- GitHub `production` Environment 사용 가능 여부
- origin domain과 Route 53 hosted zone
- GitHub `production-destroy` Environment 사용 가능 여부

현재 checkout의 `origin`과 `upstream`이 다르므로 OIDC trust에는 실제 배포를
수행하는 repository 하나만 사용한다.

### 1.2 관리자 AWS 접근

최초 bootstrap은 사람의 AWS SSO 또는 통제된 관리자 profile로 실행한다.
장기 access key를 GitHub에 복사하지 않는다.

확인 항목:

- AWS CLI 로그인 계정
- 대상 account ID와 region
- Route 53 hosted zone
- CDK v2 CLI
- Python과 프로젝트 dependency

### 1.3 GitHub Environment

repository에 `production` Environment를 만든다.

- deployment branch: `main`
- required reviewer: 단독 운영에서는 없음 권장
- `Hong1008`을 reviewer로 둘 경우 prevent self-review 비활성화
- admin bypass: 운영 정책에 따라 비활성화 권장

`production-destroy` Environment를 별도로 만든다.

- required reviewer: `Hong1008`
- 단독 운영 중에는 prevent self-review 비활성화
- 향후 별도 운영자가 추가되면 prevent self-review 활성화
- 폐기 workflow 외에는 이 Environment를 사용하지 않음

Variables:

```text
AWS_ACCOUNT_ID
AWS_REGION
AWS_DEPLOY_ROLE_ARN
AWS_AVAILABILITY_ZONE
ORIGIN_DOMAIN
HOSTED_ZONE_ID
HOSTED_ZONE_NAME
CLOUDFRONT_ORIGIN_PREFIX_LIST_ID
NGINX_IMAGE
```

AWS access key는 Secret으로 만들지 않는다.
이 값은 `production` Environment에 모두 설정한다. deploy workflow는 이를
runner의 Git 비추적 `deploy/aws/config/prod.json`으로 생성한다. `production-destroy`
Environment에는 최소한 `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`과 `RUNPOD_API_KEY`를
설정한다. `GHCR_OWNER`는 수동 workflow 입력으로 받는다.

Secrets:

```text
RUNPOD_API_KEY
```

RunPod key는 Actions에서 Pod를 관리하기 위한 값이며 API·MCP runtime에는
주입하지 않는다.

## 2. AWS bootstrap

bootstrap은 다음 순서로 한 번 수행한다.

1. `deploy/aws/bootstrap/github-oidc-role.yaml` 검토
2. AWS CLI로 OIDC provider와 deploy role stack 생성
3. trust subject가 실제 repository의 `production` 및 `production-destroy` Environment인지 확인
4. 제한된 CloudFormation execution policy 준비
5. `cdk bootstrap` 실행
6. GitHub Environment의 `AWS_DEPLOY_ROLE_ARN` 설정
7. 임시 test workflow로 OIDC role assume 확인

기본 CDK bootstrap은 asset staging용 ECR repository를 생성한다. WorkShield
application image는 이 repository에 push하지 않으며 GHCR만 사용한다.

OIDC trust 예시 subject:

```text
repo:<owner>/<repository>:environment:production
```

조직 전체나 모든 repository를 허용하지 않는다.

## 3. 운영 비밀 등록

[비밀 관리](secrets-management.md)에 따라 다음을 준비한다.

1. RunPod 운영 API key 발급
2. GitHub Environment에 `RUNPOD_API_KEY` 등록
3. `LAW_OC` 등록
4. origin header 생성
5. 필요할 때만 Hugging Face token 준비
6. Foundation stack 배포 후 `put-secrets.sh`로 `vllm`, `embed`, `origin-header`,
   `law` secret을 모두 등록

VLLM·Embedder API key는 `put-secrets.sh --generate`로 생성해 해당 Pod와 runtime에
같은 값을 사용한다. Pod endpoint와 model ID는 최초 배포 workflow가 확인·저장한다.

`deploy/aws/scripts/put-secrets.sh`는 value를 command argument로 받지 않고
대화형 입력 또는 안전한 stdin을 사용하도록 구현한다.

## 4. GHCR 최초 설정

### 4.1 최초 image 게시

CI 통과 후 build-only workflow 또는 deploy workflow의 image job으로 API와
MCP image를 게시한다.

```text
ghcr.io/<owner-lower>/skn30-4th-2team/api:<git-sha>
ghcr.io/<owner-lower>/skn30-4th-2team/mcp:<git-sha>
ghcr.io/<owner-lower>/skn30-4th-2team/embed-rerank:<git-sha>
```

확인:

- package가 source repository에 연결됨
- OCI source와 revision label 존재
- package 권한에 workflow repository가 연결됨
- package에 secret이나 `.env`가 포함되지 않음

### 4.2 visibility

공개 artifact를 전제로 package visibility를 `public`으로 설정한다. public
전환은 되돌릴 수 없으므로 image layer와 포함 corpus를 먼저 확인한다. 전환
후 EC2에서 로그인 없이 해당 SHA를 pull해 확인한다.

private package를 사용한다면 EC2 secret 준비와 `docker login` 성공을 먼저
확인한 뒤 배포한다.

## 5. AWS 인프라 최초 배포

origin TLS 때문에 두 단계로 진행한다.

### 5.1 Foundation

CDK foundation stack으로 다음을 만든다.

- IAM instance role
- security group
- EBS volumes
- Elastic IP
- Route 53 origin record
- EC2와 SSM 관리 연결
- log group과 Parameter Store namespace

EC2가 SSM managed node로 표시되는지 확인한다. SSH inbound는 열지 않는다.

### 5.2 인증서 준비

1. origin DNS가 Elastic IP를 가리키는지 확인한다.
2. EC2에서 Route 53 DNS-01로 공인 인증서를 발급한다.
3. Nginx에 인증서와 key를 연결한다.
4. Nginx가 origin header를 검증하도록 설정한다.
5. SSM session에서 `curl --resolve <origin-domain>:443:127.0.0.1`과 같은
   방식으로 인증서 hostname과 HTTPS health 응답을 확인한다.
6. 인증서 자동 갱신 timer와 reload hook을 확인한다.

CloudFront prefix list 제한을 해제하거나 임시 관리용 443 inbound를 추가하지
않는다. origin 최초 확인은 SSM session 내부에서 수행한다.

### 5.3 Service와 Edge

CDK service stack으로 다음을 배포한다.

- 비공개 S3 web bucket과 OAC
- CloudFront distribution
- S3·API cache behaviors
- SPA CloudFront Function
- CloudFront origin custom header
- origin protocol `HTTPS only`
- SSM deployment document

CloudFront distribution 생성이 완료된 뒤 기본 domain을 GitHub Environment의
배포 URL과 운영 문서에 기록한다.

## 6. 정상 배포

정상 배포는 GitHub Actions `deploy-production.yml`을 수동 실행한다.

1. main의 대상 commit과 GHCR owner를 입력해 workflow 수동 실행
2. CI 결과 확인
3. API·MCP·Embedder SHA image 게시 확인
4. production Environment 보호 규칙 통과
5. AWS foundation과 RunPod 상태 확인
6. 없는 Pod는 생성하고 기존 정상 Pod는 재사용
7. Pod readiness, 인증, Parameter Store binding 확인
8. CDK change 내용 확인
9. SSM container 배포 결과 확인
10. API live·ready 상태 확인
11. S3 web 배포 확인
12. CloudFront invalidation 완료 확인
13. 활성 release SHA 기록 확인

배포 중에는 두 번째 운영 배포가 실행되지 않아야 한다.

## 7. 컨테이너 배포 확인

SSM command 결과에서 다음만 확인한다. secret 환경값이나 전체
`docker inspect`는 출력하지 않는다.

- pull한 API·MCP image digest
- container 상태
- health status
- 활성 release SHA
- 실패 단계와 비식별 오류 코드

Compose 갱신 시 데이터 볼륨을 삭제하지 않는다. `docker compose down -v`를
운영 배포 명령에 사용하지 않는다.

## 8. 롤백

### 8.1 애플리케이션

1. 마지막 정상 release SHA를 확인한다.
2. 해당 SHA image가 GHCR에 남아 있는지 확인한다.
3. `rollback-production.yml`을 대상 SHA로 실행한다.
4. production Environment 승인을 거친다.
5. SSM이 API·MCP를 이전 SHA로 변경한다.
6. health 상태를 확인한다.
7. 활성 release SHA를 갱신한다.

### 8.2 웹

rollback workflow는 대상 release SHA를 별도 checkout해 같은 revision의 web build를
S3에 배포하고 CloudFront invalidation을 완료한다. S3 versioning은 추가 복구 수단으로
유지한다.

### 8.3 인프라

CDK rollback은 애플리케이션 rollback과 분리한다. CloudFormation stack
이벤트를 먼저 확인하고 직전 검증된 CDK revision으로 배포한다.

EBS, S3 bucket, secret을 삭제하는 change는 일반 rollback 절차로 자동
실행하지 않는다.

## 9. 비밀 회전

비밀별 순서는 [비밀 관리](secrets-management.md)를 따른다.

공통 절차:

1. 새 값 발급
2. 공급자와 Secrets Manager에 새 version 설정
3. 소비 container 또는 CloudFront 갱신
4. 실제 연결 확인
5. 이전 값 폐기
6. 회전 일자와 담당자 기록

값을 먼저 폐기한 뒤 애플리케이션을 갱신하지 않는다.

## 10. 인증서 운영

- 자동 갱신 timer 상태 확인
- 만료 경보 확인
- 갱신 후 Nginx reload 확인
- `/opt/workshield/certificates` 권한 확인
- 인증서 볼륨이 snapshot이나 image에 포함되지 않았는지 확인

갱신 실패 시 CloudFront origin 502가 발생하기 전에 DNS challenge 권한과
인증서 발급 로그를 확인한다.

## 11. 장애별 조치

| 현상 | 우선 확인 |
| --- | --- |
| CloudFront 502 | origin 인증서, Nginx, origin header, security group |
| API 403 | origin header 값과 CloudFront distribution 배포 상태 |
| API 404가 HTML로 반환 | distribution 전체 custom error 사용 여부 |
| SSE 조기 종료 | CloudFront timeout, Nginx buffering, heartbeat |
| GHCR pull 실패 | package visibility, image SHA, private token scope |
| SSM command 미도달 | SSM agent, instance role, outbound 443 |
| API not ready | MCP health, Docker network, `WORKSHIELD_MCP_URL` |
| RunPod 연결 실패 | Pod ID·base URL parameter, API key, Pod readiness, outbound 443 |
| SQLite 파일 없음 | EBS mount와 Compose volume 경로 |

## 12. 종료와 폐기

환경 제거는 GitHub Actions `destroy-production.yml`을 수동 실행한다.

1. 보존할 데이터가 없는지 확인
2. `DESTROY workshield-prod` 확인 문자열 입력
3. `production-destroy` Environment 승인
4. 저장된 ID의 RunPod Pod 삭제 확인
5. CloudFront·S3·EC2·EBS·Elastic IP·project DNS record 삭제
6. project Parameter Store 항목 삭제
7. Secrets Manager secret의 7일 후 삭제 예약
8. job summary에서 잔존 자원 확인

기본 폐기 범위에는 workflow가 만든 RunPod Pod와 project AWS stack이 포함된다.
사전 생성 RunPod template, Route 53 hosted zone, 도메인 등록, GHCR image,
GitHub OIDC provider, CDK bootstrap stack은 공유 가능성이 있어 보존한다.

Secrets Manager 즉시 강제 삭제와 bootstrap·OIDC 폐기는 별도 확인이 필요한
purge 작업으로 분리한다. 세부 순서와 멱등 규칙은
[RunPod 자동화](runpod-automation.md)를 따른다.
