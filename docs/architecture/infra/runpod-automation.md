# RunPod 자동 배포와 폐기

이 문서는 GitHub Actions가 RunPod Embedder·Reranker Pod와 vLLM Pod를
생성·확인·연결·삭제하는 계약을 정의한다. AWS 애플리케이션 배포 흐름은
[CI/CD](ci-cd.md), 비밀 저장 위치는 [비밀 관리](secrets-management.md),
운영 순서는 [운영 Runbook](operations-runbook.md)을 따른다.

## 적용 범위

기존 스크립트를 자동화의 기반으로 사용한다.

| 역할 | 기존 스크립트 |
| --- | --- |
| vLLM Pod 생성 | `deploy/llm_pod/deploy_llm_pod.py` |
| vLLM Pod 삭제 | `deploy/llm_pod/rm_llm_pod.py` |
| Embedder·Reranker Pod 생성 | `mcp/deploy/deploy_embed_pod.py` |
| Embedder·Reranker Pod 삭제 | `mcp/deploy/rm_embed_pod.py` |

고정 template ID는 초기에는 사전 준비된 외부 의존성으로 취급한다.
workflow가 만든 Pod는 삭제 대상이지만, workflow가 만들지 않은 template은
기본 삭제 대상에 포함하지 않는다. template까지 코드로 생성하게 되면 생성한
template ID도 상태에 기록하고 폐기 대상에 추가한다.

## 운영 원칙

- 상태를 `api/.env` 또는 `mcp/.env`에만 저장하지 않는다.
- 생성 script는 사람이 읽는 출력과 기계가 읽는 JSON 출력을 분리한다.
- stdout, command 표시, GitHub Actions output에 secret을 출력하지 않는다.
- 같은 환경에 대해 여러 번 실행해도 기존 정상 Pod를 재사용하는 멱등 동작을
  기본으로 한다.
- Pod를 새로 교체할 때는 새 Pod의 readiness를 확인한 뒤 AWS runtime 설정을
  전환하고 이전 Pod를 삭제한다.
- 생성 도중 실패하면 해당 실행에서 새로 만든 자원만 역순으로 정리한다.
- 모든 인프라 변경 workflow는 같은 `concurrency` group을 사용한다.

## 기존 스크립트 변경 계약

### 공통 CLI

생성 script에 다음 형태의 옵션을 추가한다.

```text
--output json
--state-backend aws
--environment prod
--name <결정적 이름>
--no-env-file
--wait
--timeout-seconds <값>
```

삭제 script는 URL에서 ID를 추론하는 방식 외에 명시적 ID를 우선 지원한다.

```text
--pod-id <id>
--state-backend aws
--environment prod
--ignore-not-found
--wait
```

로컬 개발 호환을 위해 기존 `.env` 갱신 방식은 유지할 수 있지만,
`--state-backend aws` 또는 `--no-env-file` 사용 시 로컬 `.env`를 변경하지
않는다.

### 출력

생성 성공 시 secret이 없는 JSON만 반환한다.

```json
{
  "pod_id": "<runpod-pod-id>",
  "base_url": "https://<pod-id>-8000.proxy.runpod.net",
  "model_id": "<vllm-model-id>",
  "created": true
}
```

`VLLM_API_KEY`, `HUGGING_FACE_TOKEN`, `RUNPOD_API_KEY`는 JSON과 로그에
포함하지 않는다. 현재 vLLM 생성 script가 생성한 API key와 전체 `--env`
명령을 출력하는 부분은 제거해야 한다.

## 인증과 비밀 전달

GitHub Actions는 `production` Environment secret의 `RUNPOD_API_KEY`를
`RUNPOD_API_KEY` 환경 변수로 `runpodctl`에 전달한다. `runpodctl config`로
runner 디스크에 key를 영구 저장하지 않는다.

RunPod key는 Pod 생성·조회·삭제에 필요한 최소 권한의 운영 전용 key를
사용한다. 발급 후 create/get/list/delete 동작을 확인하고 개인 개발 key와
공유하지 않는다.

vLLM API key와 Embedder API key는 workflow가 무작위로 생성한다.

- RunPod Pod에는 RunPod secret reference 또는 생성 API의 환경 변수로 주입
- AWS에서는 Secrets Manager에 저장
- API·MCP에는 EC2 instance role을 통해 root 전용 env file로 주입

workflow가 key를 생성할 때 GitHub Actions log masking을 즉시 등록하되,
masking에 의존해 값을 출력하지 않는다.

## Pod 공개 접근 보호

RunPod HTTP proxy로 노출한 포트는 인터넷에서 접근할 수 있다. 따라서 다음
검증을 운영 배포의 필수 조건으로 둔다.

- vLLM은 유효한 API key 요청만 허용한다.
- 무인증 vLLM 요청이 `401` 또는 `403`인지 확인한다.
- Embedder·Reranker의 `/runsync`에도 별도 API key 인증을 구현한다.
- MCP의 Pod 호출 client가 인증 header를 전송한다.
- 무인증 Embedder 요청이 `401` 또는 `403`인지 확인한다.

현재 Embedder·Reranker Pod 경로는 애플리케이션 인증이 없으므로 운영 자동
배포의 선행 보완 항목이다. 이를 해결하기 전에는 공개 Pod를 장시간 유지하지
않는다.

## 상태 저장

비밀이 아닌 RunPod 상태는 SSM Parameter Store에 저장한다.

```text
/workshield/prod/runpod/llm/pod-id
/workshield/prod/runpod/llm/base-url
/workshield/prod/runpod/llm/model-id
/workshield/prod/runpod/embed/pod-id
/workshield/prod/runpod/embed/base-url
```

추가로 다음 metadata를 기록한다.

```text
/workshield/prod/runpod/llm/template-id
/workshield/prod/runpod/embed/template-id
/workshield/prod/runpod/last-provision-run-id
```

삭제 workflow는 URL을 파싱하지 않고 저장된 Pod ID를 사용한다. Parameter
Store가 유실된 경우에는 결정적 Pod 이름과 소유권 tag를 이용해 조회하되,
정확히 하나로 식별되지 않으면 자동 삭제하지 않는다.

## 생성과 자동 바인딩 순서

`deploy-production.yml`의 최초 실행은 다음 순서로 수렴한다.

1. 입력값과 GitHub Environment 설정 검증
2. AWS foundation과 secret·parameter namespace 생성
3. API, MCP, Embedder·Reranker image를 GHCR에 SHA tag로 게시
4. 기존 RunPod 상태 조회
5. Embedder·Reranker Pod가 없으면 생성
6. Embedder health와 무인증 차단 확인
7. vLLM Pod가 없으면 API key를 생성하고 Pod 생성
8. vLLM health와 무인증 차단 확인
9. 인증된 `/v1/models` 응답에서 실제 model ID 확인
10. Pod ID·base URL·model ID를 Parameter Store에 기록
11. API key를 Secrets Manager에 기록
12. EC2 runtime env를 생성하고 Compose 배포
13. API→MCP→RunPod 통합 health 확인
14. Web과 CloudFront 배포

임시 vLLM URL이나 model ID로 운영 컨테이너를 시작하지 않는다. example
설정에는 `__UNSET__` 같은 명시적 placeholder를 둘 수 있지만, 실제 배포는
RunPod에서 얻은 값이 없으면 실패하도록 한다.

정상 재배포에서는 기존 건강한 Pod를 재사용한다. 매 애플리케이션 배포마다
새 GPU Pod를 만들면 중복 과금과 orphan Pod 위험이 생기므로 `replace_llm`,
`replace_embed` 입력이 명시된 경우에만 교체한다.

## readiness와 실패 처리

RunPod의 Pod 상태가 `RUNNING`이어도 내부 HTTP 서비스가 준비됐다고 간주하지
않는다. 제한 시간 동안 실제 서비스 endpoint를 지수 backoff로 확인한다.

| 대상 | 성공 조건 |
| --- | --- |
| Embedder·Reranker | 인증된 health 또는 최소 추론 요청 성공 |
| vLLM | 인증된 health와 `/v1/models` 성공 |
| 인증 방어 | 같은 endpoint의 무인증 요청이 `401` 또는 `403` |

제한 시간 초과 시 새로 만든 Pod를 삭제하고 기존 Parameter Store 값을
변경하지 않는다. 기존 Pod 교체는 새 Pod 검증과 AWS 설정 전환 후에만 이전
Pod를 삭제하는 blue/green 순서를 사용한다.

## 전체 폐기

`destroy-production.yml`은 `workflow_dispatch`만 허용하고 별도의
`production-destroy` Environment 승인을 사용한다.

삭제 순서는 다음과 같다.

1. 정확한 확인 문자열 검증
2. SSM Parameter Store에서 RunPod Pod ID를 읽어 workflow 메모리에 보관
3. RunPod Pod 삭제와 삭제 확인
4. 애플리케이션 유입 중단
5. CDK service stack 삭제
6. 임시 사용자 EBS, Elastic IP, project Route 53 record 등 foundation 삭제
7. project Parameter Store 항목 삭제
8. Secrets Manager secret을 7일 복구 기간으로 삭제 예약
9. 삭제 결과와 잔존 자원 목록 출력

Route 53 hosted zone, 도메인 등록, 사전 생성한 RunPod template, GHCR package,
GitHub OIDC provider, CDK bootstrap stack은 기본적으로 공유·외부 자원으로
보고 삭제하지 않는다. 이들까지 제거하는 작업은 별도의 `purge-bootstrap`
절차와 추가 확인을 사용한다.

Secrets Manager는 기본적으로 즉시 삭제하지 않고 7일 복구 기간을 사용한다.
복구 불가능한 즉시 삭제는 별도 `force_delete_secrets` 입력과 추가 확인이
있을 때만 허용한다.

삭제는 멱등이어야 한다. 이미 없는 Pod나 stack은 성공으로 처리하고, 다른
환경 또는 소유권을 확인할 수 없는 자원은 삭제하지 않는다.

## 공식 참고

- [RunPod API key 관리](https://docs.runpod.io/get-started/api-keys)
- [RunPod Pod 생성 API](https://docs.runpod.io/api-reference/pods/POST/pods)
- [RunPod Pod 삭제 API](https://docs.runpod.io/api-reference/pods/DELETE/pods/podId)
- [RunPodCTL Pod 명령](https://docs.runpod.io/runpodctl/reference/runpodctl-pod)
- [RunPod Pod 포트 공개와 보안](https://docs.runpod.io/pods/configuration/expose-ports)
- [AWS Secrets Manager secret 삭제](https://docs.aws.amazon.com/secretsmanager/latest/userguide/manage_delete-secret.html)
