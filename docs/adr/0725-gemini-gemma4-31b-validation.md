# 0725 Gemini Gemma 4 31B 연동 검증

- 상태: 로컬 평가용 조건부 승인, 운영 사용 금지
- 결정일: 2026-07-25
- 대상 브랜치: `feat/mvp-api`
- provider: `gemini`
- 검증 모델: `gemma-4-31b-it`
- 현행 상태: Historical evaluation only. Gemini는 현행 질문 분류 또는 답변 생성
  provider가 아니며, 현행 역할은 `0730-langgraph-chat-prompt-routing.md`를 따른다.
- 관련 ADR:
  - `0724-llm-risk.md`
  - `0724-mvp-api-completion.md`
  - `0725-ollama-qwen35-4b-validation.md`

## 맥락

로컬 Ollama Qwen3.5 4B Q4_K_M 평가에서 Chat은 구조화 출력을
통과했지만 Suggestions가 필수 출처 ID를 반복해서 누락했다. 같은
MCP 검토·grounding fixture와 같은 서버 검증 조건에서 Gemini API의
`gemma-4-31b-it`를 비교해 모델 크기와 provider 차이가 구조화 출력
준수율에 미치는 영향을 확인했다.

이번 결과는 모델의 법률 판단 능력을 평가하지 않는다. 다음 API 계약과
안전 경계만 검증한다.

- Pydantic 구조화 출력
- 비어 있지 않은 Chat answer와 허용된 출처 ID
- Suggestions의 정확한 표준조항·grounding source ID
- 내부 매칭 점수 비노출
- `NONE`을 동일·적절·문제없음·안전함으로 과장하지 않는 표현
- 출처 누락·변조 시 `LLM_OUTPUT_INVALID` 차단

## 검증 환경

| 항목 | 값 |
|---|---|
| provider | Google Gemini API |
| 모델 | `gemma-4-31b-it` |
| API 환경 | `APP_ENV=local` |
| reasoning | `OFF` |
| 구조화 출력 | LangChain `with_structured_output()` |
| 테스트 fixture | 고정 MCP 검토 결과 1조항 |
| grounding fixture | 고정 법령 참고 원문 1건 |
| API 키 | 설정 여부만 확인, 값·로그 미출력 |

실제 Gemini 호출에는 사용자 조항, 대응 표준조항과 고정 grounding
fixture가 외부 API로 전송됐다. 실제 사용자 계약서로 운영 검증한 결과가
아니며 민감정보가 없는 합성 데이터만 사용했다.

## 재현 명령

현재 `.env.local`과 비추적 `.env`에서 provider, model과 API 키를
준비한 뒤 다음 명령을 실행한다.

```text
cd api
RUN_LLM_INTEGRATION=1 \
LLM_INTEGRATION_PROVIDER=gemini \
LLM_INTEGRATION_MODEL=gemma-4-31b-it \
LLM_TEST_TIMEOUT=180 \
.venv/bin/pytest -q -m integration \
tests/integration/test_real_llm_flow.py -s
```

테스트는 provider와 model만 명시적으로 덮어쓰고 API 키는 Pydantic
Settings의 비밀 설정에서 읽는다. 테스트 로그에는 키를 출력하지 않는다.

## 사전 구조화 출력 확인

프로덕션 `create_chat_model()`로 모델을 만들고
`ChatStructuredOutput`을 직접 호출했다.

- 결과: 성공
- 최초 응답 시간: 5.063초
- outcome: `ANSWERED`
- 허용된 `USER_CLAUSE` ID 생성
- Pydantic DTO 파싱 성공

## 초기 비교 결과

Ollama 평가 후 보완된 answer·출처 필수 규칙과 내부 점수 제거를 적용한
상태에서 세 번 반복했다.

| 반복 | Chat | Chat 시간 | Suggestions | Suggestions 시간 |
|---:|---|---:|---|---:|
| 1 | 통과 | 5.466초 | 통과 | 4.873초 |
| 2 | 통과 | 5.180초 | 통과 | 4.865초 |
| 3 | 통과 | 4.869초 | 통과 | 3.958초 |

구조화 출력과 출처 ID는 6건 모두 통과했다. 다만 Chat이 `NONE`을
“일치”, “적절한 검토 후보”로 표현했다. 이는 구조 검증과 별개인 제품
표현 오류다.

## 표현 경계 보완

Chat 프롬프트와 품질 게이트에 다음 규칙을 추가했다.

- `NONE`은 동일함·적절함·문제없음·안전함을 뜻하지 않는다.
- “일치”, “적절”, “문제없음”, “안전” 표현을 사용하지 않는다.
- “표준 대응 후보가 확인됨”으로만 설명한다.
- 실제 Chat 결과에 금지 문자열이 포함되면 통합 테스트를 실패시킨다.

## 최종 반복 결과

표현 경계 보완 후 같은 품질 게이트를 세 번 반복했다.

| 반복 | Chat | Chat 시간 | Suggestions | Suggestions 시간 |
|---:|---|---:|---|---:|
| 1 | 통과 | 3.300초 | 통과 | 5.707초 |
| 2 | 통과 | 2.386초 | 통과 | 5.181초 |
| 3 | 통과 | 2.385초 | 통과 | 5.215초 |

요약:

- Chat 성공률: 3/3
- Suggestions 성공률: 3/3
- 전체 구조·출처·표현 게이트: 6/6
- Chat 중앙값: 2.386초
- Suggestions 중앙값: 5.215초
- 내부 점수 노출: 0건
- 허용 목록 밖 또는 누락 출처: 0건
- 금지 표현: 0건

Chat은 매번 “표준 대응 후보가 확인됨” 범위로 답했고,
Suggestions는 매번 다음 ID를 정확히 반환했다.

```text
standard_clause_ids = ["std_liability_1"]
grounding_source_ids = ["law_1"]
```

## Ollama Qwen3.5 4B 비교

| 항목 | Ollama Qwen3.5 4B Q4_K_M | Gemini Gemma 4 31B |
|---|---|---|
| Chat 구조·출처 | 통과 | 3/3 통과 |
| Chat 표현 경계 | 추가 평가 필요 | 최종 3/3 통과 |
| Suggestions 구조·출처 | 반복 실패 | 3/3 통과 |
| 실패 결과 서버 차단 | 정상 | 해당 없음 |
| 데이터 위치 | 로컬 Ollama | 외부 Gemini API |
| 운영 정책 | 허용 provider | 현재 운영 금지 provider |

Gemma 4 31B가 이 단일 fixture에서는 구조화 출력과 지연 모두 더 좋은
결과를 보였다. 하지만 모델 크기, 원격 추론 인프라와 네트워크 조건이
동시에 달라 provider 자체의 우열로 일반화할 수 없다.

## 결정

`gemma-4-31b-it`를 로컬 개발·비민감 fixture 평가 모델로 조건부
승인한다.

운영 기본 모델로는 승인하지 않는다.

- 현재 설정 검증은 `APP_ENV=prod`에서 `LLM_PROVIDER=ollama`만 허용한다.
- Gemini 사용 시 계약 조항과 grounding이 외부 API로 전송된다.
- 사용자 동의, 데이터 처리 위치, 보존 정책과 개인정보 영향 평가가
  합의되지 않았다.
- 단일 조항 fixture 세 번은 운영 품질을 대표하지 않는다.

따라서 운영 제한을 완화하거나 `.env.prod`의 provider를 변경하지 않는다.

## 권장 후속 작업

1. 비민감 합성 fixture로 Chat 20건, Suggestions 20건 이상을 평가한다.
2. `NONE`, `EXTRA`, `NO_MATCH`, MISSING과 주의 신호 조합별 금지 표현을
   검사한다.
3. 성공률, 허용 ID 정확도, 금지 표현 발생률과 p50·p95 지연을 기록한다.
4. 실제 사용자 데이터의 외부 Gemini 전송을 검토하려면 보안·개인정보
   합의를 별도 ADR로 먼저 승인한다.
5. 같은 평가 세트를 더 큰 로컬 모델에도 실행해 데이터 외부 전송 없이
   Gemma 4 31B 수준의 구조화 출력 준수율을 얻을 수 있는지 비교한다.

## 해석 제한

모든 응답은 표준계약서 대비 검토 후보와 참고 설명이다. 테스트 통과는
특정 조항의 동일성, 적절성, 합법성, 안전성 또는 계약상 유불리를
의미하지 않는다.
