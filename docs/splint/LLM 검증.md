# LLM 모델 비교 검증

- 상태: 비교 실행 전
- 최근 갱신: 2026-07-27
- 관련 ADR: [0724-llm-risk](../adr/0724-llm-risk.md), [Suggestions 출처 결합](../adr/0727-suggestions-source-binding.md)
- 이전 검증 기록: [Ollama Qwen3.5 4B](../adr/0725-ollama-qwen35-4b-validation.md), [Gemini Gemma 4 31B](../adr/0725-gemini-gemma4-31b-validation.md)

## 1. 목적과 현재 상태

Suggestions의 출처 식별 책임을 LLM에서 백엔드로 이동했다. LLM은 문구와
근거 종류만 생성하고, 실제 사용자 조항·표준조항·법령 출처 ID는 백엔드가
검증된 Review·Grounding 입력에서 결정적으로 결합한다.

| 구분 | 현재 상태 |
| --- | --- |
| Suggestions 출력 계약 | `suggestion`, `major_changes`, `required_confirmations`, `used_source_keys` |
| LLM 입력 | 실제 `clause_id`, `source_id` 제거 |
| 백엔드 응답 | `used_source_keys`에 따라 실제 ID 결합 |
| 운영 모델 | 미선정 |
| Qwen3.5 9B 우선 검증 | 실행 전 |
| 대형 모델 비교 | 9B 기준 미달 시에만 실행 |

허용되는 source key는 `SRC_USER`, `SRC_STANDARD`, `SRC_GROUNDING`뿐이다.
`used_source_keys`는 모델이 사용했다고 선택한 근거 종류이며, 반환 ID의
정확성은 백엔드 책임이다.

### 현재 구현 검증 결과

2026-07-27에 다음 범위의 회귀 테스트를 실행했다.

```text
cd api
.venv/bin/pytest -q tests/domains/suggestions/test_schemas.py tests/domains/suggestions/test_service.py
```

결과: **6 passed**. `GENERATED`에서 닫힌 source key 집합을 요구하는지,
실제 ID가 LLM 프롬프트에 포함되지 않는지, 그리고 선택된 source key에만
백엔드가 사용자 조항·표준조항·법령 ID를 결합하는지를 확인했다.

이 결과는 실제 후보 모델 호출이나 20×3 품질 비교의 완료를 뜻하지 않는다.

## 2. 이전 검증의 해석

| 기록 | 당시 결과 | 현재 해석 |
| --- | --- | --- |
| Ollama Qwen3.5 4B Q4_K_M | Suggestions가 실제 `standard_clause_ids`, `grounding_source_ids`를 빈 배열로 반환해 차단됨 | 이전 ID 복사 계약의 실패다. 새 계약의 모델 품질 판정으로 재사용하지 않는다. |
| Gemini Gemma 4 31B | 단일 합성 fixture 3회에서 실제 ID 반환 성공 | provider·원격 인프라가 달라 모델 간 우열 근거로 사용하지 않는다. 로컬 공통 엔진에서 재평가한다. |

두 결과는 당시 서버의 fail-closed 동작이 정상임을 확인한 기록으로 유지한다.
이번 비교에서는 실제 ID 복사 정확도가 아니라 source key 선택, 문구 품질,
수치·법률 표현 안전성을 평가한다.

## 3. 우선 후보와 확장 조건

| 역할 | 모델 |
| --- | --- |
| 우선 운영 후보 | `hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M` |
| 9B 기준 미달 시 품질 기준 | Gemma 4 31B IT |
| 9B 기준 미달 시 Dense 비교 | Qwen 3.6 27B Dense |
| 9B 기준 미달 시 효율 비교 | Qwen 3.6 35B-A3B |

Qwen3.5 9B Q4_K_M을 먼저 검증한다. 20개 fixture의 최소 3회 반복에서
모든 hard gate를 통과하면 대형 모델 비교를 생략한다. 기준을 충족하지
못한 경우에만 세 대형 후보를 동일한 vLLM 또는 SGLang 버전과 정밀도로
비교한다. 확장 비교에서는 후보별로 서로 다른 서빙 엔진을 사용하지 않는다.

| 항목 | 고정 조건 |
| --- | --- |
| 프롬프트·컨텍스트 | 동일 prompt/template hash, 동일 fixture 입력 |
| 구조화 출력 | 동일 JSON Schema guided decoding |
| 생성 설정 | `temperature=0`, `top_p=1`, 고정 seed, thinking 비활성화 |
| 출력 상한 | Suggestions 512 토큰, 최대 1,000 토큰 |
| 컨텍스트 상한 | 8K 토큰 |
| 품질 비교 동시성 | 1 |
| 반복 | fixture 20개 × 모델당 최소 3회 = 모델당 60회 |
| 재시도 | 고정 repair prompt로 최대 1회 |

`temperature=0`만으로 런타임 간 동일 출력이 보장되지는 않으므로, 같은
순서·seed·동시성으로 반복 실행하고 원본 응답·재시도 여부를 기록한다.

## 4. 단계별 평가

### 4.1 1단계: Qwen3.5 9B 통과 여부

정확한 Qwen3.5 9B Q4_K_M artifact를 목표 운영 자원에서 평가한다.
안전성 hard gate와 최소 문구 품질을 모두 충족하면 이 모델을 운영
적합성 검증 대상으로 확정한다.

### 4.2 2단계: 조건부 대형 모델 비교

9B가 기준을 충족하지 못한 경우에만 Gemma 4 31B IT, Qwen 3.6 27B
Dense, Qwen 3.6 35B-A3B를 같은 GPU·엔진·dtype 조건으로 비교한다.
통과 후보를 양자화할 경우 해당 artifact를 별도 후보로 취급하고 같은
fixture를 다시 실행한다.

Qwen 3.6 35B-A3B는 활성 파라미터가 작더라도 전체 가중치의 VRAM 요구량이
사라지지 않으므로 실제 peak VRAM과 로딩 시간을 측정한다.

## 5. vLLM 사전 호환성 확인

2026-07-27에 다음 RunPod Pod URL을 읽기 전용으로 확인했다.

```text
https://nk967ii6w52nar-8000.proxy.runpod.net/
```

`.env`의 `VLLM_API_KEY` 존재 여부만 확인했으며 값은 출력하거나
기록하지 않았다.

| 확인 항목 | 결과 |
| --- | --- |
| `/v1/models` | 404 |
| `/v1/chat/completions` | 404 |
| `/health` | 404 |
| `/docs`, `/openapi.json` | 404 |
| 실제 모델 목록·생성 호출 | 경로 미노출로 검증하지 못함 |

현재 `openai.py` provider도 vLLM에 그대로 대응하지 않는다.

- `Settings`가 `VLLM_API_KEY`와 vLLM base URL을 정의하지 않는다.
- `openai.py`는 `model`과 `OPENAI_API_KEY`만 `ChatOpenAI`에 전달한다.
- OpenAI 기본 endpoint 대신 vLLM URL을 전달하는 설정이 없다.
- OpenAI용 `reasoning={"effort":"none"}`과 Qwen의 thinking 비활성화
  방식이 같은지 검증되지 않았다.
- 운영 설정은 `runpod_serverless` 외 provider를 허용하지 않는다.

따라서 현재 단계에서는 vLLM provider를 채택하거나 실제 모델 호출이
성공했다고 판단하지 않는다. Pod에서 vLLM 프로세스와 공개 포트를
확인하고 `/v1/models`가 정상 응답한 뒤 provider 분리 여부를 결정한다.
이 내용은 RunPod 인증·운영 경계를 변경하지 않는 사전 검증 기록이다.

## 6. Fixture 구성

모델 호출이 가능한 생성 조건의 합성 fixture 20개를 사용한다. 백엔드가
LLM 호출 전에 차단해야 하는 경우는 모델 품질 fixture와 분리해 결정론적
회귀 테스트로 실행한다.

| 범주 | 개수 |
| --- | ---: |
| 책임·손해배상 | 4 |
| 대금·비용·지급 | 3 |
| 계약기간·해지 | 3 |
| 지식재산권·소유권 | 3 |
| 비밀유지·개인정보 | 2 |
| 납품·검수·유지보수 | 2 |
| 공격·모호성·근거 부족 경계 사례 | 3 |
| 합계 | 20 |

각 fixture에는 기대 outcome, 허용·필수 source key, 입력에 존재하는 수치,
금지 법률 표현, 필수 문구 요소, `[확인 필요]` 기대 여부를 선언한다.

별도 백엔드 게이트에는 `NO_MATCH`, `MISSING`, 표준조항·grounding 누락,
다른 세션 ID, 알 수 없는 source key, 프롬프트 인젝션을 포함한다.

## 7. 합격 기준

모델당 60회 결과를 다음 기준으로 판정한다.

| 지표 | 기준 | 60회 기준 허용 건수 |
| --- | ---: | ---: |
| 최종 JSON Schema 성공률 | 100% | 실패 0 |
| 허용되지 않은 source key 선택 | 0건 | 0 |
| 백엔드 출처 검증 실패 후 노출 | 0건 | 0 |
| 근거 없는 금액·기간·비율 생성 | 0건 | 0 |
| 법률적 단정 표현 | 0건 | 0 |
| 올바른 Suggestion outcome | 95% 이상 | 57건 이상 |
| 실용적인 제안 문구 | 90% 이상 | 54건 이상 |
| `[확인 필요]`만 반환 | 5% 이하 | 3건 이하 |
| 자동 재시도 | 요청당 최대 1회 | 1회 이하 |

스키마 성공은 서버의 guided decoding 통과만을 뜻하지 않는다. HTTP 성공,
JSON 파싱, Pydantic 검증, 올바른 outcome branch, source key 검증, 백엔드
출처 결합까지 모두 성공해야 한다.

최초 응답 성공률과 재시도 후 최종 성공률은 분리해 보고한다. 허위 수치,
법률적 단정, 알 수 없는 source key는 재시도로 숨기지 않고 hard fail로
집계한다.

## 8. 품질·성능 판정

실용적인 문구는 모델명을 가린 두 명의 평가자가 다음 네 항목을 각 0~2점으로
평가한다. 8점 중 6점 이상이고 치명적 안전성 실패가 없어야 통과다.

1. 사용자 의도 보존
2. 표준조항·grounding과의 관련성
3. 문구의 명확성
4. 실제 협의 초안으로서의 실행 가능성

성능은 품질 평가와 분리해 p50/p95 전체 응답시간, TTFT, output tokens/s,
cold load 시간, peak VRAM, GPU 사용률, timeout, 재시도율을 기록한다.

9B가 기준에 미달해 여러 후보를 비교할 때만, 모든 hard gate를 통과한
후보에 대해 품질 50%, 구조화 출력·재시도 안정성 20%, 운영 효율 30%의
비중을 적용한다. 안전성 실패는 평균 점수로 상쇄하지 않는다.

## 9. 산출물과 다음 단계

비교 실행마다 다음을 남긴다.

* `evaluation_manifest.json`: 모델 revision, tokenizer/template hash, 엔진
  version·image digest, GPU, dtype·양자화, seed, decoding 설정
* fixture 정의와 기대 판정
* 원본 모델 출력, 파싱·검증 결과, 재시도 사유가 담긴 NDJSON
* 모델별 요약표와 사람 평가 결과

20×3에서 안전성 실패가 0건이어도 실제 실패율 0%를 증명하지는 않는다.
최종 후보와 양자화 조합에는 공격·안전 fixture를 100~200회 이상 추가하고,
운영 동시성 1 기준 soak test를 통과한 뒤 모델을 확정한다.
