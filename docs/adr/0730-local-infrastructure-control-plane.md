# 로컬 인프라 control plane과 직접 EC2 origin

- 상태: Accepted
- 날짜: 2026-07-30

## 맥락

기존 production workflow가 CloudFormation, EC2, IAM, Secrets Manager와
RunPod lifecycle까지 직접 변경했다. 배포 실패 범위가 애플리케이션 release를
넘어갔고 RunPod 관리 키와 runtime secret의 책임도 GitHub에 결합됐다.
단일 production EC2를 사용하는 현재 규모에서는 별도 ALB의 운영 비용과
구성이 health routing 이점보다 컸다.

## 결정

- AWS bootstrap/CDK deploy·destroy, RunPod와 runtime secret lifecycle은 로컬
  root `justfile`에서만 실행한다.
- GitHub OIDC role은 기존 EC2의 고정 SSM Document, 지정 S3 bucket과 지정
  CloudFront distribution에 대한 application deploy 권한만 갖는다.
- CloudFront는 private S3와 DuckDNS 이름의 EC2 Nginx origin을 직접 사용한다.
  EC2 ingress는 CloudFront origin-facing prefix list의 443으로 제한하고
  별도 origin header와 TLS를 함께 검증한다.
- AWS와 RunPod는 결정적 이름, tag, template ID와 immutable 설정으로
  재발견한다. 로컬 state는 cache와 실패 보상 journal일 뿐 소유권 원장이
  아니다.
- Container와 Web rollback은 기존 검증 artifact를 재활성화하며 rebuild하지
  않는다.

## 결과

애플리케이션 workflow에서 CloudFormation·EC2·IAM·Secrets 조회와 RunPod
관리 권한이 제거된다. 로컬 운영에는 더 높은 권한과 명시적 확인 절차가
필요하지만 변경 주체와 실패 보상 범위가 분명해진다.

ALB가 없으므로 다중 instance, target health 기반 자동 우회와 무중단 instance
교체는 지원하지 않는다. traffic이나 가용성 요구가 단일 EC2 범위를 넘으면
ALB/ECS 등 별도 구조를 새 ADR로 검토한다.
