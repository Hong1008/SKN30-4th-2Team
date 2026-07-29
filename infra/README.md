# WorkShield infrastructure control plane

이 디렉터리는 로컬 운영자가 AWS CDK와 RunPod lifecycle을 관리하기 위한 내부
구현이다. 공개 실행 인터페이스는 저장소 root의 `just infra-*` 명령뿐이며
`src/workshield_infra` 모듈을 직접 실행하는 방법은 지원하지 않는다.

- `config/`: 비밀이 아닌 배포 설정 예제와 Git 비추적 secret 예제
- `assets/`: EC2에 설치되는 Compose, Nginx, release runtime 자산
- `src/workshield_infra/providers/`: AWS와 RunPod adapter
- `src/workshield_infra/stacks/`: Access, Foundation, Service CDK stack
- `tests/`: 외부 계정에 연결하지 않는 결정론적 단위·policy test

설치와 운영 순서는 [설치 가이드](../docs/infra/getting-started.md)에서 시작한다.
AWS나 RunPod를 직접 호출하는 검증은 unit test에 포함하지 않는다.
