# 0727 RunPod Pod·Serverless 운영 경계 및 인증 결정

- 상태: Accepted
- 결정일: 2026-07-27
- 관련 문서: [0724 LLM 리스크 관리](0724-llm-risk.md), [0725 Ollama Qwen3.5 4B 검증](0725-ollama-qwen35-4b-validation.md)

## 1. 배경

운영 모델 후보인 `hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M`를 RunPod Pod의 Ollama로 검증하려 했다. 초기 구성은 Pod HTTP Proxy 앞단에 애플리케이션 API 키 프록시를 두고, API 및 MCP가 커스텀 헤더로 키를 전달하는 방식이었다.

RunPod Pod의 HTTP Proxy는 인터넷에 공개되는 ingress이며, 포트를 노출한 Pod에는 애플리케이션 차원의 인증·인가를 구현해야 한다는 안내가 있다. 다만 이 경로에서 실제 키를 포함한 요청이 컨테이너까지 도달하지 못하는 문제가 발생했다. [RunPod Pod 포트 노출 문서](https://docs.runpod.io/pods/configuration/expose-ports)

## 2. 오늘의 트러블슈팅 결과

| 구분 | 확인 결과 | 해석 |
| --- | --- | --- |
| Ollama 상태 확인 | `/health`는 정상 응답했고, 올바른 모델 목록 경로는 `/api/tags`였다. | 컨테이너 및 기본 포트 노출 자체는 동작한다. |
| Pod 내부 프록시 | Pod 내부에서 올바른 키를 포함한 요청은 모델 목록을 정상 반환했다. | Ollama 및 인증 프록시 구현은 정상 동작했다. |
| 외부 HTTP Proxy | 실제 키를 포함한 `Authorization` 및 `X-API-Key` 요청은 403 Cloudflare 응답이었고, 임의 키는 애플리케이션의 401 응답이었다. | 실제 키 값이 컨테이너 프록시에 도달하기 전에 edge에서 차단된 것으로 보인다. 이는 관측 결과에 근거한 추론이다. |
| 키 변경 반영 | Pod 재시작만으로는 템플릿 환경변수 변경이 반영되지 않았고, Pod 재생성 후 새 키와 환경변수의 지문이 일치했다. | Pod 환경변수 교체는 재생성이 필요하다. |
| MCP 리랭커 | 테스트 흐름 일부는 완료됐지만, 원격 MCP Pod의 `/runsync` 요청에서 404 로그가 확인됐다. | 완료 결과만으로 원격 리랭커 호출 성공을 판단할 수 없으며, 별도 검증이 필요하다. |

따라서 문제의 중심은 Ollama 프로세스나 헤더 검증 코드가 아니라 Pod HTTP Proxy 앞단의 실제 비밀값 헤더 처리 경로로 판단했다. 동일한 프록시 경로에서 헤더 이름만 바꾸는 방식은 해결책이 아니었다.

## 3. 결정

### 3.1 Pod는 로컬 운영 모델 검증용으로만 사용한다

RunPod Pod는 모델 동작 검증과 비용 절감을 위한 단기 환경으로 사용한다.

- Ollama Pod 및 MCP 임베딩·리랭커 Pod에서 애플리케이션 자체 API 키 인증을 제거한다.
- Pod는 운영 트래픽, 민감 데이터, 장기 공개 엔드포인트 용도로 사용하지 않는다.
- 검증이 끝난 Pod는 중지 또는 삭제하여 비용과 노출 시간을 줄인다.
- 공개 HTTP Proxy를 사용하는 동안에는 모델 검증 범위를 비민감 데이터로 제한한다.

이 결정은 Pod가 안전한 운영 ingress라는 뜻이 아니라, 해당 용도의 보안 요구사항을 적용하지 않는다는 명확한 사용 경계다.

### 3.2 운영 및 시연은 RunPod Serverless를 사용한다

운영 또는 외부 시연에서 사용하는 모델 호출은 RunPod Serverless Endpoint로 전환한다.

- API는 `LLM_PROVIDER=runpod_serverless`일 때 RunPod Serverless API를 호출한다.
- 인증은 `RUNPOD_API_KEY`의 `Authorization: Bearer` 방식과 Endpoint ID를 사용한다.
- 별도의 Pod API 키, HMAC 서명, 커스텀 인증 프록시는 추가하지 않는다.
- RunPod API 키는 필요한 Serverless 권한만 가진 restricted key로 발급·보관한다.

RunPod API 키는 RunPod의 API 및 Serverless Endpoint 요청을 인증하는 자격 증명이다. Pod HTTP Proxy의 애플리케이션 접근 제어를 자동으로 대신하지는 않는다. [API 키 및 restricted key 문서](https://docs.runpod.io/get-started/api-keys), [Serverless 요청 인증 문서](https://docs.runpod.io/public-endpoints/requests)

### 3.3 MCP도 동일한 경계를 적용한다

- MCP의 Pod URL(`RUNPOD_POD_BASE_URL`) 사용 시에는 인증 헤더를 보내지 않는다.
- MCP의 Serverless Endpoint 사용 시에는 `RUNPOD_API_KEY`를 Bearer 토큰으로 사용한다.
- 기존 `RUNPOD_POD_API_KEY`와 `POD_API_KEY` 환경변수 및 관련 헤더 구현은 제거한다.

## 4. 반영한 구현

- Ollama Pod 이미지와 시작 스크립트에서 Go 인증 프록시 및 `POD_API_KEY` 의존성을 제거했다.
- MCP Pod 서버의 HMAC/커스텀 API 키 검증을 제거했고, Pod 호출용 헤더도 `Content-Type`만 남겼다.
- API에 `runpod_serverless` LLM provider를 추가했다. Ollama 호환 `/api/chat` 요청을 Serverless handler 입력으로 전달하고, structured output도 기존 API 서비스 인터페이스에 맞춰 처리한다.
- 운영 환경에서는 `LLM_PROVIDER=runpod_serverless`만 허용하도록 설정 검증을 추가했다.
- 모델을 이미지에 포함하는 Serverless worker와 통합 배포 명령을 추가했다.

Serverless worker는 RunPod의 custom handler 형태로 동작하며, handler 입력을 로컬 Ollama `/api/chat`에 전달한다. [RunPod handler 함수 문서](https://docs.runpod.io/serverless/development/handler-functions)

## 5. 배포 절차

필요한 환경변수는 다음과 같다.

```dotenv
RUNPOD_API_KEY=<restricted-serverless-key>
RUNPOD_OLLAMA_SERVERLESS_IMAGE=<registry-image>
RUNPOD_OLLAMA_SERVERLESS_TEMPLATE_ID=<template-id>
RUNPOD_OLLAMA_ENDPOINT_ID=<endpoint-id>

APP_ENV=prod
LLM_PROVIDER=runpod_serverless
LLM_MODEL=hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M
LLM_TIMEOUT_SECONDS=600
```

이미지 빌드·푸시·Serverless 템플릿·Endpoint 생성을 한 번에 실행할 수 있다.

```bash
just ollama-serverless-deploy
```

명령 실행 결과의 Endpoint ID는 자동으로 `.env`를 수정하지 않으므로, 확인 후 API 환경변수 `RUNPOD_OLLAMA_ENDPOINT_ID`에 반영한다. Serverless Endpoint의 생성·관리 방식은 [RunPod Serverless CLI 문서](https://docs.runpod.io/runpodctl/reference/runpodctl-serverless)를 따른다.

## 6. 후속 검증 및 유의사항

- 실제 Serverless Endpoint를 배포한 뒤 API의 구조화된 채팅·추천 흐름과 MCP 임베딩/리랭커 호출을 각각 실환경에서 검증한다.
- Serverless의 콜드 스타트와 모델 로딩 시간을 고려해 운영 호출 timeout은 600초로 둔다. 시연 요구사항에 맞춰 minimum worker 수와 idle timeout을 조정한다.
- Pod를 다시 운영 ingress로 사용해야 한다면, provider의 edge 정책과 호환되는 인증 경로를 별도로 확정한 뒤 재설계한다. 이번에 제거한 raw secret header 방식은 재도입하지 않는다.
- 원격 MCP Pod의 `/runsync` 404 원인은 이 ADR의 인증 전략과 별개로, endpoint 경로·배포 이미지·Pod 상태를 확인해 해소한다.
