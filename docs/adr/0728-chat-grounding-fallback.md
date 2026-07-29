# 0728 Chat·Suggestions 단계별 근거 사용과 법령 조회 fallback

- 상태: Accepted
- 결정일: 2026-07-28
- 관련 문서:
  - [0724 LLM 리스크 관리](0724-llm-risk.md)
  - [0724 MVP API 완성](0724-mvp-api-completion.md)
  - [0727 Suggestions 출처 선택과 백엔드 결정적 결합](0727-suggestions-source-binding.md)
  - [프론트엔드 세션 Cookie 연동](../api/frontend-session-cookie-handoff.md)

## 1. 배경

결과 기반 질의응답과 협의 문구 생성은 현재 Review에 저장된 사용자
조항, 대응 표준조항 후보와 필요 시 조회한 법령 원문만 사용한다.

기존 Chat은 특정 사용자 조항이 선택된 경우에만 해당 조항의
`category`로 `get_category_grounding`을 호출했다. 전체 검토 결과를
대상으로 질문하면 `focus_clause_id`가 없기 때문에 법령 조회를 수행하지
않았다.

기존 Suggestions는 사용자 조항과 대응 표준조항이 있어도 법령 조회
상태가 `OK`가 아니면 즉시 `INSUFFICIENT_GROUNDING`을 반환했다. 이
정책은 근거 없는 법률 결론을 차단하는 데에는 안전하지만 다음과 같은
설명·협의 요청까지 과도하게 제한했다.

- 사용자 조항과 대응 표준조항의 차이 설명
- 검토 결과의 별도 확인 후보 요약
- 계약 체결 전에 확인할 질문 작성
- 사용자·표준조항을 기반으로 한 협의 문구 초안

법령 원문이 조회되지 않았다는 사실은 사용자·표준조항 근거도 없다는
뜻이 아니다. 또한 MCP의 `NO_RESULT`, `UNMAPPED_CATEGORY`,
`UPSTREAM_ERROR`, `TIMEOUT`은 서로 다른 상태이며 이를 “관련 법령이
없음”으로 해석해서는 안 된다.

실제 수동 검증에서는 다음 문제도 확인했다.

- `scrollIntoView()` 반환값이 React effect cleanup으로 전달되어
  `destroy is not a function`이 발생함
- 본문이 없는 제한 응답이 다음 Chat 요청의 `history`에 포함되어 API
  최소 길이 검증에서 `422`가 발생함
- 모델이 답변 가능한 전체 검토 질문에서 잘못된 출처 ID 또는 빈 출처를
  반환해 `LLM_OUTPUT_INVALID`로 안전 차단됨
- `korean-law MCP`의 `search_law` 오류로 `SCOPE_SOW` category의 법령
  조회가 실패함
- 사용자·표준조항 비교 답변에서 “실행 가능성이 낮다”와 같이 제공된
  근거를 넘어선 평가 표현이 생성됨

## 2. 결정

근거를 사용자 조항, 표준조항, 법령 원문의 단계로 구분한다. 법령
원문은 답변을 보강하는 선택적 근거이며, 설명·비교·협의 문구 생성의
일률적인 필수 조건으로 사용하지 않는다.

### 2.1 Chat의 근거 단계

| 확보된 근거 | 허용 범위 |
| --- | --- |
| 사용자 조항 | 원문 요약, 확인 질문 |
| 사용자 조항 + 대응 표준조항 | 표준 대비 설명, 차이, 협의 방향 |
| 사용자 조항 + 표준조항 + 법령 원문 | 관련 법령 원문을 포함한 참고 설명 |
| 사용자·표준조항 근거 없음 | `INSUFFICIENT_GROUNDING` |
| 합법·위법·승소 가능성 등 법률 결론 요구 | `REFUSED` |

“가장 불리한 조항”과 같은 질문은 유불리를 단정하지 않고 “표준 대비
별도 확인이 필요한 검토 후보”로 재구성해 설명한다. `NONE`도 안전이나
적절함을 뜻하지 않으며 “표준 대응 후보가 확인됨”으로만 표현한다.

Chat의 `ANSWERED`는 비어 있지 않은 답변과 현재 Review·Grounding
allowlist에 존재하는 출처를 반드시 포함해야 한다. 출처 검증에
실패하면 기존과 같이 `LLM_OUTPUT_INVALID`로 차단한다.

### 2.2 Chat의 MCP 법령 조회

특정 조항 질문은 기존과 같이 대상 조항의 검증된 `category`로
`get_category_grounding`을 호출한다.

전체 검토 질문은 질문에 법령·법률·조문 등 법령 원문을 명시적으로
요청하는 표현이 있을 때만 MCP를 호출한다. 서버는 현재 Review 결과에
실제로 존재하는 category만 사용하며 중복을 제거하고 한 요청에서 최대
3개까지만 조회한다.

```text
일반 전체 질문
  → Review 결과만 사용

법령을 명시한 전체 질문
  → 현재 Review category 최대 3개 선택
  → get_category_grounding 병렬 호출
  → OK인 원문만 LAW allowlist에 추가
```

법령 조회가 `OK`가 아니더라도 사용자·표준조항으로 가능한 설명은
`ANSWERED`로 반환하고 법령 원문이 확인되지 않았음을 `limitations`와
`tool_status`에 표시한다. 질문이 법령 원문 자체만 요구하고 조회된
원문이 없으면 법령을 추측하지 않고 제한 응답을 반환한다.

### 2.3 Suggestions의 법령 fallback

Suggestions는 대상 사용자 조항과 `CANDIDATE_SELECTED` 대응 표준조항이
있으면 법령 조회가 `OK`가 아니어도 협의 문구를 생성할 수 있다.

- `OK`: `SRC_USER`, `SRC_STANDARD`, 필요 시 `SRC_GROUNDING` 사용
- `NO_RESULT`, `UNMAPPED_CATEGORY`, `TIMEOUT`, `UPSTREAM_ERROR`:
  `SRC_USER`, `SRC_STANDARD`만 사용
- 법령 미확인 상태는 `required_confirmations`의
  `law_grounding` 항목으로 결정적으로 추가
- 법령 원문이 없는데 모델이 `SRC_GROUNDING`을 선택하면
  `LLM_OUTPUT_INVALID`로 차단

법령 조회 실패를 법령 부재로 표시하거나 법률 적용 여부를 추측하지
않는다. Suggestions의 실제 사용자·표준·법령 출처 ID는 기존 ADR
`0727-suggestions-source-binding.md`에 따라 백엔드가 결정적으로
결합한다.

### 2.4 프론트엔드 요청 안정성

React effect는 cleanup 함수 외의 값을 반환하지 않도록 블록 본문을
사용한다. Chat history는 공백을 제거한 뒤 본문이 1자 이상인 메시지만
API로 전송한다.

이 결정은 다음 오류를 방지한다.

- Promise를 cleanup으로 오인하는 React 런타임 오류
- 빈 assistant 메시지로 인한 후속 Chat 요청 `422`

## 3. 검증

다음 자동화 검증을 수행했다.

```text
cd api
uv run pytest -q \
  tests/domains/chat/test_service.py \
  tests/domains/suggestions/test_service.py \
  tests/api_v1/test_mvp_routes.py

uv run ruff check \
  app/domains/chat \
  app/domains/suggestions \
  tests/domains/chat \
  tests/domains/suggestions
```

결과는 `11 passed`, Ruff 통과다.

검증 항목은 다음과 같다.

- 법령 `NO_RESULT`에서도 사용자·표준조항 기반 Chat 답변 허용
- 법령을 명시한 전체 질문에서 현재 Review category로 MCP 호출
- 일반 전체 질문에서 불필요한 법령 MCP 호출 생략
- 법령 `NO_RESULT`에서도 사용자·표준조항 기반 Suggestions 생성
- 조회되지 않은 법령에 대한 `SRC_GROUNDING` 선택 차단
- 실제 출처 ID의 백엔드 결정적 결합 유지

프런트엔드는 `npm.cmd run typecheck`를 통과했다.

전체 API 테스트는 `231 passed`, `4 skipped`, `1 failed`였다. 실패한
기존 테스트는 운영 환경 provider를 `ollama`로 생성하지만 현재 설정은
운영에서 `runpod_serverless`만 허용하는 정책 불일치로, 이번 결정의
Chat·Suggestions 변경과 무관하다.

실제 외부 LLM 통합 테스트는 외부 provider로 fixture가 전송될 수 있어
별도 명시적 승인 전에는 실행하지 않는다.

## 4. 수동 검증 결과

### 4.1 개선된 부분

사용자 조항과 대응 표준조항을 함께 인용하고 두 조항의 차이를 설명하는
응답이 생성됐다. 이전의 사용자 조항 중심 일반 설명보다 비교 대상과
출처가 명확해졌다.

### 4.2 남은 품질 문제

다음은 안전 차단이 정상 작동한 경우지만 사용자 경험은 개선이 필요하다.

- 답변 가능한 전체 요약 질문이 출처 검증 실패로
  `LLM_OUTPUT_INVALID`가 됨
- “표준조항이 체계를 요구한다”, “실행 가능성이 낮다”처럼 근거를
  넘어선 평가 표현이 생성됨
- 법령 조회 실패 안내가 category별 실제 상태보다 일반적인 제한
  문구로 표시됨

실제 법령 질문에서는 `korean-law MCP`의 `search_law` 호출이 실패했고,
서버는 법령 원문을 추측하지 않고 제한 응답을 반환했다. 이 안전 동작은
유지하되 하위 MCP 연결 문제는 별도로 복구한다.

## 5. 결과

### 긍정적 결과

- 법령 조회 가능 여부와 사용자·표준조항 설명 가능 여부를 분리한다.
- 설명·비교·협의 요청의 불필요한 거절을 줄인다.
- 법령이 없거나 실패했다는 잘못된 단정을 방지한다.
- 법령 원문을 명시적으로 요청할 때만 MCP를 호출해 불필요한 지연을
  제한한다.
- 조회되지 않은 법령 출처를 모델이 주장할 수 없다.

### 비용과 한계

- 질문의 법령 조회 필요 여부는 현재 제한된 키워드로 판별한다.
- 전체 질문은 최대 3개 category만 조회하므로 관련 category가 그 이후에
  있으면 법령 원문이 포함되지 않을 수 있다.
- 모델의 출처 ID 복사 실패로 `LLM_OUTPUT_INVALID`가 발생할 수 있다.
- 출력 문장이 근거 범위를 넘어선 평가 표현을 포함하는지 결정적으로
  검증하지 않는다.
- `korean-law MCP` 장애 시 법령 기반 답변은 계속 제한된다.

## 6. 검토한 대안

### 6.1 법령 `OK`를 모든 생성의 필수 조건으로 유지

채택하지 않았다. 사용자·표준조항만으로 가능한 설명과 협의 문구까지
차단하고 MCP 가용성이 전체 기능의 단일 장애점이 된다.

### 6.2 모든 Chat 질문에서 모든 category 법령 조회

채택하지 않았다. 불필요한 MCP 호출, 응답 지연과 upstream 장애 노출이
증가한다. 법령을 명시한 전체 질문과 특정 조항 질문에서만 조회한다.

### 6.3 법령 조회 실패 시 모델이 일반 법률 지식으로 보완

채택하지 않았다. 현재 Review·Grounding allowlist 밖의 법령을 생성할
수 있어 출처 검증과 제품의 비자문 경계를 위반한다.

## 7. 후속 작업

1. Chat 출처 검증 실패 시 허용 출처를 명시한 1회 재생성과 결정론적
   요약 fallback을 설계한다.
2. Chat도 Suggestions처럼 모델이 실제 ID를 복사하지 않는 source key
   또는 요청별 opaque key 방식을 검토한다.
3. “실행 가능성이 낮다”, “법적으로 요구한다” 등 근거 밖 평가 표현을
   차단하거나 재작성하는 출력 검증을 추가한다.
4. category별 Grounding 상태를 서버가 결정적으로 limitations에
   결합한다.
5. `korean-law MCP search_law` 연결 실패 원인을 별도 진단한다.
6. 운영 provider 정책과 불일치하는 기존 테스트를 정리한다.
7. 승인된 비민감 fixture로 실제 후보 LLM의 답변률, 올바른 거절률,
   출처 정확도와 응답 시간을 평가한다.

## 8. 재검토 조건

다음 상황에서 이 결정을 다시 검토한다.

- 법령 원문 없이 생성한 협의 문구의 품질이 기준을 충족하지 못함
- 법령 키워드 방식의 category 선택 누락이 반복됨
- category 조회 상한 3개로 필요한 법령 원문을 제공하지 못함
- Chat의 `LLM_OUTPUT_INVALID` 비율이 운영 기준을 초과함
- 법률 결론 또는 근거 밖 평가 표현의 차단률이 기준을 충족하지 못함
