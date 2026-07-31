# 0728 운영 LLM을 RunPod vLLM으로 전환

- 상태: Accepted
- 결정일: 2026-07-28
- 대체 결정: `0727-runpod-shxt.md`의 운영·시연 Serverless 채택 결정

## 1. 배경

RunPod Serverless Ollama 구성은 콜드 스타트 지연과 운영 요금 부담이
있다. 운영 모델을 지속 기동하는 RunPod Pod의 vLLM OpenAI-compatible
server로 전환하고 API의 Chat/Suggestions 구조화 출력 계약을 유지한다.

## 2. 결정

- 운영 환경(`APP_ENV=prod`)에서는 `LLM_PROVIDER=vllm`만 허용한다.
- `runpod_serverless` 구현은 재현과 롤백을 위해 남기지만 운영에서는
  선택할 수 없다.
- vLLM은 별도 provider로 분리하되 HTTP client는 LangChain
  `ChatOpenAI`의 OpenAI-compatible 지원을 재사용한다.
- 인증은 `VLLM_API_KEY`, 접속 주소는 `VLLM_BASE_URL`로 분리한다.
- Qwen thinking은 요청의 `chat_template_kwargs.enable_thinking`으로
  제어하며 OpenAI 전용 reasoning payload를 보내지 않는다.
- Chat/Suggestions 구조화 출력은 Chat Completions의 JSON Schema
  response format을 사용한다.
- 이 vLLM 모델은 최종 답변과 제안 문구 생성만 담당한다. 질문 유형 분류는
  현행 구성에서 OpenAI가 현재 질문의 앞 80자만 받아 수행하며, 계약서 원문,
  조항, 검토 결과와 대화 이력은 OpenAI에 보내지 않는다. 세부 결정은
  `0730-langgraph-chat-prompt-routing.md`를 따른다.

## 3. 운영 설정

```dotenv
APP_ENV=prod
LLM_PROVIDER=vllm
LLM_MODEL=<GET /v1/models가 반환하는 model ID>
VLLM_BASE_URL=https://<pod-id>-8000.proxy.runpod.net
VLLM_API_KEY=<vllm --api-key와 일치하는 비밀값>
LLM_TIMEOUT_SECONDS=180

# 질문 분류 전용: OpenAI, 답변 모델과 분리
ROUTER_LLM_PROVIDER=openai
ROUTER_LLM_MODEL=<승인된 OpenAI 분류 모델>
ROUTER_LLM_TIMEOUT_SECONDS=3
```

`VLLM_BASE_URL`은 origin과 `/v1` API root를 모두 허용하며 API 내부에서
`/v1` root로 정규화한다.

`OPENAI_API_KEY`는 router provider의 비밀값으로 별도 주입한다. 로컬 분류
모델로 전환할 때는 `ROUTER_LLM_PROVIDER=vllm`과 해당 모델 ID를 함께
설정하고, OpenAI 키를 제거할 수 있다.

## 4. 배포 게이트

운영 트래픽을 연결하기 전에 아래 항목을 모두 통과해야 한다.

1. 인증 없는 `GET /v1/models`가 401 또는 403을 반환한다.
2. 올바른 Bearer token을 사용한 `GET /v1/models`가 200을 반환한다.
3. 반환된 model ID와 `LLM_MODEL`이 일치한다.
4. `POST /v1/chat/completions` 일반 호출이 성공한다.
5. `enable_thinking=false` 호출에 thinking 본문이 섞이지 않는다.
6. Chat과 Suggestions의 JSON Schema structured output이 성공한다.
7. timeout·401·404 응답에서 API 키가 로그와 오류에 노출되지 않는다.

2026-07-27 확인한 기존 endpoint는 모든 경로에서 404를 반환했으므로,
Pod 포트와 프록시 routing이 정상화되기 전에는 이 게이트를 통과한 것으로
간주하지 않는다.

## 5. 구현 후 검증

2026-07-28 같은 endpoint를 OpenAI SDK 요청 형태로 다시 확인한 결과
`GET /v1/models`가 200을 반환했고 설정된 model ID와 일치했다. 새
provider를 통한 최소 JSON Schema 호출과 WorkShield Chat/Suggestions
실환경 통합 테스트 2건도 통과했다.

Python `urllib` 기본 User-Agent는 RunPod/Cloudflare edge에서 403으로
차단되므로 운영 애플리케이션은 검증된 `ChatOpenAI` provider 경로를
사용한다.
