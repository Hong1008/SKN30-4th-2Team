# 비밀 관리

비밀의 원본은 운영자 로컬의 Git 비추적 파일에만 둔다. EC2가 소비해야 하는
값은 로컬 `just` 명령으로 AWS Secrets Manager에 동기화한다. GitHub
Actions는 secret 값을 생성하거나 읽지 않는다.

## 로컬 원본

기본 파일은 `infra/config/prod.secrets.env`이며 권한을 제한한다.

```bash
chmod 600 infra/config/prod.secrets.env
```

예제에는 key 이름과 빈 placeholder만 포함하고 실제 값은 넣지 않는다.

| 이름 | 용도 | runtime 전달 |
| --- | --- | --- |
| `RUNPOD_MANAGEMENT_API_KEY` | 로컬 RunPod Pod 조회·생성·삭제 | 전달하지 않음 |
| `VLLM_API_KEY` | `infra-ensure`가 최초 생성, API에서 vLLM Pod 호출 | API |
| `RUNPOD_EMBED_API_KEY` | `infra-ensure`가 최초 생성, MCP에서 Embed/Rerank Pod 호출 | MCP |
| `ORIGIN_HEADER` | CloudFront→Nginx origin 검증 | Nginx/CloudFront |
| `LAW_OC` | 법령 API 호출 | MCP |
| `DUCKDNS_TOKEN` | origin DNS와 DNS-01 갱신 | 필요한 운영 경로 |
| `HUGGING_FACE_TOKEN` | 제한 모델 download | 필요할 때만 Pod |

Legacy RunPod Serverless provider를 사용하는 환경만 호출용
`RUNPOD_SERVERLESS_API_KEY`를 별도로 등록한다. 이 값은 Pod lifecycle 권한을
가진 관리 키와 같아서는 안 된다. 이전의 모호한 `RUNPOD_API_KEY` 이름은
사용하지 않는다.

## 저장 위치

| 값 종류 | 저장 위치 |
| --- | --- |
| 원본 secret | 운영자 password manager와 Git 비추적 secret 파일 |
| EC2 runtime secret | AWS Secrets Manager |
| RunPod 관리 키 | 운영자 로컬만 |
| Pod ID, endpoint, model ID, 활성 release | 비밀이 아닌 SSM runtime binding |
| AWS region, role ARN, SSM Document, bucket, distribution ID | GitHub Environment Variable |

GitHub Secret에 다음을 저장하지 않는다.

```text
RUNPOD_MANAGEMENT_API_KEY
VLLM_API_KEY
RUNPOD_EMBED_API_KEY
RUNPOD_SERVERLESS_API_KEY
ORIGIN_HEADER
LAW_OC
DUCKDNS_TOKEN
HUGGING_FACE_TOKEN
AWS access key
```

SSM Parameter Store에는 secret 값을 넣지 않는다. `/workshield/prod/runtime`
binding에는 Pod ID, URL, model ID, release tag/digest처럼 비밀이 아닌 값만
기록한다.

## 최초 생성과 동기화

두 Pod 호출 키는 사용자가 입력하지 않는다. `infra-ensure`가 account·region·
environment lock 안에서 빈 값을 생성하여 `prod.secrets.env`에 0600 권한으로
원자 저장하고, 동일한 값을 candidate Pod 인증에 사용한다. readiness와
무인증 차단 검증이 끝나면 그 값을 AWS Secrets Manager에 동기화한다.

다른 runtime secret을 수동 변경했거나 기존 호출 키를 다시 동기화할 때만
다음 명령을 별도로 실행한다. 두 호출 키가 아직 생성되지 않았다면 이 명령은
실패하며 최초 생성 대신 사용할 수 없다.

```bash
just infra-secrets-sync profile=<profile> environment=prod
```

- command argument로 secret 값을 전달하지 않는다.
- shell tracing(`set -x`)을 사용하지 않는다.
- CloudFormation output, CDK context, tag, journal에 값을 기록하지 않는다.
- 동기화 후에는 secret 이름과 version 상태만 확인한다.

RunPod 관리 키는 동기화 대상에서 제외한다. 로컬 provider 또는 MCP submodule
lifecycle 스크립트를 호출하는 동안에만 process environment로 전달하고 EC2
환경 파일에는 쓰지 않는다.

개별 Pod 삭제나 image 교체에서는 호출 키를 유지한다. 전체 `infra-destroy`가
소유 Pod 제거와 AWS secret 삭제 예약을 모두 완료한 경우에만 로컬 파일의
`VLLM_API_KEY`, `RUNPOD_EMBED_API_KEY` 값을 비운다. 실패한 폐기는 복구할 수
있도록 기존 값을 보존한다.

## 회전

자동 회전은 WorkShield가 직접 생성할 수 있는 Pod 호출 키만 지원한다.

```bash
just infra-secrets-rotate vllm profile=<profile> environment=prod
just infra-secrets-rotate embed profile=<profile> environment=prod
```

공통 순서는 다음과 같다.

1. 공급자에서 새 값을 발급하거나 로컬에서 안전하게 생성한다.
2. Secrets Manager pending version에 기록한다.
3. 새 값을 사용하는 candidate 또는 소비 경로를 검증한다.
4. current version과 runtime binding을 전환한다.
5. 현재 container tag를 재적용하고 health를 확인한다.
6. 이전 값을 폐기하고 비밀값이 아닌 회전 일시·담당자만 기록한다.

이 명령은 pending version 생성, 새 키를 가진 candidate Pod 검증, current
승격, runtime binding 전환, 활성 container release 재적용과 health 확인,
기존 Pod 제거 순으로 실행한다. 실패하면 이전 secret version과 binding을
복원하고 이번 candidate만 제거한다.

`ORIGIN_HEADER` 회전은 CloudFront origin 설정과 Nginx가 잠시 양쪽 값을
허용하도록 단계적으로 진행한 뒤 이전 값을 제거한다. `DUCKDNS_TOKEN`은 DNS
갱신과 인증서 갱신을 모두 검증한 뒤 이전 값을 폐기한다. `LAW_OC`,
`ORIGIN_HEADER`, `DUCKDNS_TOKEN`처럼 외부 조정이 필요한 값은 자동 회전
대상이 아니며, 공급자에서 값을 발급하고 단계별 운영 계획을 검토한 후
`infra-secrets-sync`를 사용한다.

RunPod 관리 키는 유출 의심 시 즉시 공급자에서 폐기하고 로컬 원본만
교체한다. AWS와 GitHub에는 반영할 값이 없어야 한다.

## 유출 대응

1. 해당 공급자에서 key를 revoke한다.
2. Git history, workflow log, CloudFormation event, SSM command output 노출을
   확인한다.
3. 새 값을 발급하고 정상 회전 절차로 소비자를 복구한다.
4. 관리 키가 runtime이나 GitHub에 들어갔다면 Pod lifecycle 권한으로 발생한
   변경 내역도 감사한다.
5. 실제 값은 사고 문서에 복사하지 않는다.
