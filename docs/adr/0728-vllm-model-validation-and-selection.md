# 0728 vLLM 모델 검증·선정과 운영 생성 정책

- 상태: Accepted
- 결정일: 2026-07-28
- 관련 ADR:
  - [0728 운영 LLM을 RunPod vLLM으로 전환](0728-vllm-production-provider.md)
  - [0727 Suggestions 출처 선택과 백엔드 결정적 결합](0727-suggestions-source-binding.md)
  - [0724 LLM 리스크 관리](0724-llm-risk.md)
- 관련 검증 문서:
  - [LLM 검증](../splint/LLM%20검증.md)
  - [Qwen3.5 9B FP8 dynamic 검증 결과](../splint/LLM%20검증%20결과%20-%20RedHatAI%20Qwen3.5%209B%20FP8%20dynamic.md)
  - [Gemma 4 12B FP8 Dynamic 검증 결과](../splint/LLM%20검증%20결과%20-%20RedHatAI%20gemma%204%2012B%20it%20FP8%20Dynamic.md)
  - [EXAONE 3.5 7.8B AWQ 검증 결과](../splint/LLM%20검증%20결과%20-%20LGAI%20EXAONE%203.5%207.8B%20Instruct%20AWQ.md)

## 1. 맥락

RunPod Serverless는 콜드 스타트와 요금 부담 때문에 운영 후보에서 제외하고,
지속 기동하는 RunPod Pod의 vLLM OpenAI-compatible endpoint를 사용하기로
했다. provider 전환 이후에는 WorkShield의 제한된 LLM 역할에 적합한 모델을
같은 조건으로 비교하고 다음 항목을 운영 정책으로 확정할 필요가 있었다.

- MCP 품질평가와 LLM 평가의 중복 범위
- 전문가가 없는 부트캠프 프로젝트에서의 품질 판정 방식
- 구조화 출력 repair와 backend hard gate
- 생성 token 상한과 timeout
- latency, TTFT, token usage와 재현성 artifact 수집
- 운영 모델 선정

LLM은 MCP 결과를 변경하거나 법률 판단을 내리지 않고, 검증된 사용자 조항,
표준조항과 grounding 안에서 Suggestions 협의 문구를 생성하는 역할만 맡는다.

## 2. 결정

### 2.1 운영 provider와 모델

- 운영 provider는 `vllm`을 사용한다.
- 운영 모델은 `RedHatAI/Qwen3.5-9B-FP8-dynamic`으로 선정한다.
- `RedHatAI/gemma-4-12B-it-FP8-Dynamic`,
  `LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct`,
  `LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct-AWQ`는 현재 설정에서 운영
  후보로 채택하지 않는다.
- `runpod_serverless` 구현은 재현과 롤백 목적으로 남기되 운영 정책에서는
  사용하지 않는다.

Qwen의 모델 ID는 인증된 `GET /v1/models`가 반환하는 값과 정확히 일치해야
한다. endpoint readiness는 `/version` 응답만으로 판단하지 않고
`/v1/models`에서 목표 모델이 안정적으로 조회되는 시점으로 판단한다.

### 2.2 평가 범위

MCP의 결정론적 품질은 기존 `mcp/quality` 결과를 재사용하며 API에서 같은
fixture 전체를 다시 품질평가하지 않는다.

API LLM 평가는 MCP fixture를 참조하는 8개 얇은 overlay를 각 2회 실행한다.

- 책임·손해배상
- 대금·지급
- 계약 해지
- 지식재산권
- 비밀유지
- 업무 범위
- 수치 grounding
- 프롬프트 인젝션

총 16회 중 최소 15회가 구조·기대값을 통과하고 hard gate 실패가 없어야
PASS다. 법률 전문가 평가는 필수 게이트로 두지 않는다. 개발 관점의 출력
점검으로 충분하지 않은 모호한 사례에만 Subagent 평가를 선택적으로 사용한다.

### 2.3 생성 token 상한

모델 비교 평가에서는 `max_completion_tokens=1000`을 사용해 각 모델이
자연스럽게 종료하는 실제 token 분포와 `finish_reason`을 수집한다.

1000은 목표 생성량이 아니라 비교용 상한이다. 상한을 채우지 않고
`finish_reason=stop`으로 끝나면 실제 생성 token만 사용한다.

Qwen의 1000-token 평가에서 관측된 completion token은 다음과 같다.

- p50: 165
- p95: 255
- 최대: 255
- `finish_reason=stop`: 18/18

따라서 현재 Suggestions 운영 상한은 512를 유지한다. 평가기의 비교 상한
1000과 운영 상한 512를 구분한다. 출력 분포 또는 schema가 바뀌면 다시
측정하며, 모델을 통과시키기 위한 단순 상한 증가는 허용하지 않는다.

### 2.4 thinking과 구조화 출력

- thinking은 OFF로 고정한다.
- vLLM 요청에는
  `chat_template_kwargs.enable_thinking=false`를 전달한다.
- OpenAI 전용 reasoning payload는 vLLM에 전달하지 않는다.
- Suggestions는 Chat Completions의 JSON Schema structured output을
  사용한다.
- temperature 0, top_p 1, seed 42로 평가한다.
- 평가 concurrency는 1로 두어 호출별 성능과 token metric을 분리한다.

### 2.5 production repair

repair prompt는 평가 전용이 아니라 운영 Suggestions 경로에 둔다.

- 요청당 최초 호출과 repair를 합쳐 최대 2회만 허용한다.
- JSON, Pydantic, 구조 오류는 한 번 repair할 수 있다.
- 중국어·러시아어 문자 혼입은 고정 언어 repair를 한 번 적용한다.
- 허용되지 않은 source key는 repair하지 않고 차단한다.
- 길이 종료 결과를 이어 쓰거나 일부 completion을 조합하지 않는다.
- timeout은 repair하지 않고 외부 서비스 timeout으로 처리한다.

Qwen은 책임 fixture의 최초 출력 2건에서 `major_changes`에 중국어 `免责`를
생성했다. 언어 gate와 repair가 이를 제거한 뒤 최종 결과가 통과했으므로 해당
방어 로직을 제거하지 않는다.

### 2.6 backend hard gate

다음 조건을 생성 후 백엔드에서 결정론적으로 검사한다.

- 실제 내부 사용자·표준조항·grounding ID 노출
- 허용되지 않은 source key
- 원문과 `provided_inputs`에 없는 금액·기간·비율
- 합법·위법·불법 등 법률 결론 단정
- 중국어 CJK ideograph 또는 러시아어 Cyrillic 문자
- 구조화 출력 schema 위반

출처 ID는 LLM이 생성하지 않는다. LLM은 `SRC_USER`, `SRC_STANDARD`,
`SRC_GROUNDING` 중 사용한 근거 종류만 선택하고, 백엔드가 현재 요청의
검증된 실제 ID를 결정적으로 결합한다.

### 2.7 timeout과 실패 처리

- 현재 평가와 Suggestions 운영 게이트에서는 60초 안에 완료되지 않은
  호출을 `LLM_TIMEOUT` 실패로 처리한다.
- timeout 한 건이 전체 평가 suite를 중단하지 않으며 개별 실패로 기록하고
  다음 fixture를 계속 실행한다.
- timeout이나 불완전 JSON을 사용자 결과로 반환하지 않는다.
- timeout을 피하기 위해 생성 상한을 무조건 늘리지 않는다.

기존 vLLM provider ADR의 `LLM_TIMEOUT_SECONDS=180` 예시는 이번 모델 선정
게이트의 60초 기준으로 대체한다. 실제 운영 환경에서 값을 변경하려면 latency
SLO와 비용을 함께 재검증한다.

### 2.8 성능과 artifact 수집

평가기에는 다음 정보를 로컬 artifact로 남긴다.

- fixture·반복별 latency
- 호출별 prompt, completion, total tokens
- 호출별 `finish_reason`
- repair 여부와 시도별 elapsed time
- 전체 p50, p95, max latency
- vLLM 평균 TTFT와 generation token metric
- model ID, vLLM version, 생성 설정, prompt·fixture hash
- Git commit과 dirty 상태
- `runpodctl`로 조회한 GPU, image, Pod metadata

RunPod metadata의 환경변수, token, API key와 secret 필드는 저장 전에
redact한다. 평가 산출물은 로컬 전용 ignored directory에 두며 비밀값을
커밋하지 않는다.

로컬 평가 스크립트가 `api/.env`의 `VLLM_BASE_URL`, `VLLM_API_KEY`를 읽는
것은 허용한다. 이 비밀값은 로컬 실행에만 사용하고 stdout, 오류 본문,
manifest와 결과 artifact에는 기록하지 않는다.

metadata HTTP 조회는 RunPod proxy에서 불안정했던 `urllib` 대신 실제 모델
호출과 같은 계열의 `httpx`를 사용한다.

## 3. 모델 비교 결과

모든 전체 평가는 같은 8개 fixture, 각 2회, thinking OFF, JSON Schema,
temperature 0, top_p 1, seed 42 기준으로 수행했다.

| 모델 | 평가 조건 | 결과 | 주요 실패 |
| --- | --- | ---: | --- |
| Qwen3.5 9B FP8 dynamic | 1000 tokens | 16/16 PASS | 최초 중국어 2건을 repair |
| Gemma 4 12B FP8 Dynamic | 1000 tokens | 12/16 FAIL | 지급 timeout 2건, `귀책` 미반영 2건 |
| EXAONE 3.5 7.8B Instruct | 1000 tokens dry-run | 0/2 | 모두 1000 tokens에서 `length` |
| EXAONE 3.5 7.8B Instruct AWQ | 1000 tokens | 2/16 FAIL | 14건이 1000 tokens에서 `length` |

### 3.1 Qwen

- 16/16 통과, hard gate 실패 0
- repair 2회
- latency p50 7.102초, p95 16.416초
- completion token p50 165, p95·최대 255
- 프롬프트 인젝션, 내부 ID, 혼합 언어, 근거 없는 수치 최종 위반 0

### 3.2 Gemma

512-token 평가에서는 11/16, 1000-token 평가에서는 12/16이었다. 상한을
늘리자 길이 오류는 없어졌지만 지급 2건이 60초 timeout으로 바뀌었다.
latency p50은 24.888초, p95는 60.042초였고 구조화 출력 상당수에서 줄바꿈
대신 독립 문자 `n`이 생성됐다.

### 3.3 EXAONE

비양자화 모델은 책임 dry-run 2건이 모두 정확히 1000 tokens에서
`finish_reason=length`로 끝났다.

AWQ 모델은 책임 dry-run 2건을 각각 217 tokens에서 정상 종료해 전체 평가를
진행했다. 그러나 다른 7개 fixture의 14건은 모두 1000 tokens에서
`finish_reason=length`로 끝났다. 단일 dry-run 성공만으로 전체 범주 적합성을
판정하지 않는다.

## 4. 결과

### 장점

- MCP 품질평가를 반복하지 않고 LLM 경계에 집중해 개발 부담을 제한한다.
- 모델마다 같은 schema, fixture와 안전성 gate를 적용해 비교 가능성을 높인다.
- 작은 모델도 문자열 ID 복사가 아닌 협의 문구 생성 품질에 집중한다.
- token과 finish reason을 호출별로 기록해 길이 오류와 모델 품질 실패를
  구분한다.
- repair와 hard gate가 모델의 언어 혼입 및 불완전 출력을 fail-closed로
  처리한다.
- Qwen은 다른 후보보다 짧고 안정적으로 구조화 출력을 종료했다.

### 비용과 제약

- Qwen도 책임 문맥에서 중국어 혼입이 있어 repair 호출과 latency가 증가한다.
- 8개 fixture, 16회는 실제 실패율 0%를 통계적으로 증명하지 않는다.
- 합성 grounding을 사용했으며 법률 전문가 타당성 평가는 수행하지 않았다.
- model revision, tokenizer hash와 image digest는 아직 고정하지 못했다.
- 콜드 스타트와 장시간 soak test는 측정하지 않았다.
- RunPod Pod는 지속 기동 비용과 공개 proxy 운영 보안 관리가 필요하다.

## 5. 검토한 대안

### 5.1 RunPod Serverless 유지

채택하지 않았다. 부트캠프 프로젝트에서 콜드 스타트와 요금 부담이 크다.

### 5.2 Gemma 채택

채택하지 않았다. 1000-token에서도 timeout과 형식 품질 문제가 남고 Qwen보다
느리며 통과율이 낮다.

### 5.3 EXAONE 또는 EXAONE AWQ 채택

채택하지 않았다. 일부 fixture는 성공하지만 대부분 JSON Schema 생성을
상한 안에 종료하지 못한다.

### 5.4 모든 모델의 운영 상한을 1000으로 고정

채택하지 않았다. 1000은 모델 비교와 분포 측정에 사용한다. 선정된 Qwen의
최대 completion이 255이므로 운영 상한 512가 충분하고 runaway 출력 범위를
더 작게 유지할 수 있다.

### 5.5 전문가 또는 LLM Judge를 필수화

채택하지 않았다. 전문가가 없는 프로젝트 상황과 토큰 비용을 고려해 자동
gate와 제한된 개발자 점검을 기본으로 한다. 모호한 사례에만 선택적으로
Subagent를 사용한다.

## 6. 재검토 조건

다음 상황에서는 모델 또는 운영 설정을 다시 검토한다.

- Qwen의 timeout, repair 또는 hard gate 실패율이 운영 기준을 초과함
- Suggestions schema나 prompt가 변경되어 completion token p95가 증가함
- Chat 실호출에서 Suggestions와 다른 실패 양상이 관측됨
- RunPod GPU, vLLM version, chat template 또는 모델 revision이 변경됨
- model revision과 image digest를 고정한 재현성 검증이 필요함
- 더 저렴한 후보가 동일 16회 게이트와 실제 데모 latency 기준을 통과함

재검토 시 MCP 품질 fixture 전체를 다시 실행하지 않고, 변경이 LLM 경계에만
있다면 동일한 얇은 API overlay부터 실행한다.
