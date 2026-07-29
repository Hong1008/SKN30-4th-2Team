# 2026-07-29 AWS·RunPod 배포 시험

이 문서는 2026-07-29에 수행한 일회성 연결·배포 시험 기록이다. 현재 설치
절차나 원하는 상태를 정의하지 않는다. 현재 절차는
[인프라 문서](../../infra/README.md)를 따른다.

## 목적과 환경

- AWS 서울 region에서 Foundation/Service CDK stack 생성과 폐기 확인
- GitHub OIDC, GHCR, SSM Run Command, S3/CloudFront 연결 확인
- DuckDNS origin과 DNS-01 TLS 확인
- RunPod vLLM 및 Embed/Rerank Pod 연결 확인
- API·MCP container와 Web release 검증 시도

실제 account ID, instance ID, IP, distribution ID, bucket 이름, command ID,
Pod ID와 credential은 이 이력에서 제외했다. 리소스 식별자는 당시 로그에서만
조회하며 현재 리소스로 재사용하지 않는다.

## 완료된 항목

- GitHub OIDC provider와 제한 전 deploy role, CDK bootstrap을 생성했다.
- Route 53을 사용하지 않고 DuckDNS를 CloudFront→EC2 origin 이름으로
  사용하는 구성을 확인했다.
- Foundation 배포 중 IAM role 권한과 Security Group ASCII 제약을 수정한 뒤
  stack 생성을 완료했다.
- Service 배포 중 S3 auto-delete custom resource의 Lambda 권한 누락을 수정한
  뒤 EC2, private S3, CloudFront와 SSM Document 생성을 완료했다.
- DuckDNS DNS-01 Let’s Encrypt 인증서를 발급하고 EC2에 설치했다. 일일 갱신
  timer와 Nginx reload 경로를 구성했다.
- EC2에 Docker Engine과 Compose v2, secret 없는 runtime asset을 설치했다.
- API·MCP SHA image를 GHCR에 게시하고 package를 public으로 전환한 뒤 익명
  pull 흐름을 확인했다.
- vLLM과 Embed/Rerank Pod를 생성해 RunPod 수준의 실행 상태를 확인했다.

## 발견된 문제

1. 최초 container release는 vLLM endpoint가 placeholder 상태여서 중단됐다.
2. 최초 Embed GPU 종류를 확보할 수 없어 대체 GPU를 수동 선택해야 했다.
3. Embed/Rerank endpoint가 인증 요청과 무인증 요청을 모두 허용했다. Bearer
   인증 요구사항을 충족하지 못한 상태에서 정상 binding으로 인정할 수 없었다.
4. EC2 기본 image에는 Docker와 Compose가 준비되지 않아 runtime 설치
   절차가 필요했다.
5. 고정하려던 Nginx digest가 registry에 존재하지 않아 검증된 공식 digest로
   바꿔야 했다.
6. MCP는 단독 health가 성공했지만 FastMCP DNS rebinding 보호가 Compose의
   `Host: mcp:8000` 요청을 `421`로 거부했다. API가 재시작해 end-to-end
   container release는 정상 완료되지 않았다.
7. runtime GHCR owner parameter 누락으로 한 차례 SSM release가 실패했다.
8. Web release, CloudFront viewer 경로, rollback workflow는 검증하지 못했다.

Container release command와 활성 release 기록은 일부 수행됐지만 API health가
통과하지 않았으므로 유효한 production release로 간주하지 않는다.

## 시험 종료와 폐기

시험 종료 후 비용이 발생하는 프로젝트 리소스를 폐기했다.

- RunPod vLLM 및 Embed/Rerank Pod 제거를 확인했다.
- Service stack을 먼저, Foundation stack을 다음 순서로 삭제했다.
- EC2, Elastic IP, CloudFront distribution, Web bucket, WorkShield EBS,
  project SSM parameter와 NAT Gateway가 남지 않은 것을 확인했다.
- 프로젝트 Secrets Manager secret은 즉시 삭제하지 않고 7일 복구 유예로
  삭제 예약했다.
- 공유 가능성이 있는 CDK bootstrap, GitHub OIDC/deploy role, GitHub
  Environment, GHCR package와 DuckDNS record는 보존했다.

삭제 시점의 DuckDNS record는 반환된 Elastic IP를 계속 가리킬 수 있으므로
현재 origin으로 사용해서는 안 된다. CDK bootstrap의 빈 ECR repository와
소량의 S3 staging asset은 남아 소액 저장 비용이 발생할 수 있다.

## 이후 설계에 반영한 사항

- 인프라 생성·삭제와 RunPod lifecycle은 GitHub Actions에서 로컬 `just`
  명령으로 이동한다.
- GitHub deploy role에서 CloudFormation·EC2·IAM·Secrets 권한을 제거한다.
- EC2 runtime asset 설치는 로컬 provisioning에 포함한다.
- RunPod candidate는 readiness뿐 아니라 무인증 거부까지 확인한 후 binding을
  전환한다.
- MCP Compose host allowlist와 API→MCP 네트워크 입력 경계를 통합 검증한다.
- Container rollback은 기존 GHCR tag/digest, Web rollback은 보존된 S3
  artifact를 재활성화하며 다시 build하지 않는다.

