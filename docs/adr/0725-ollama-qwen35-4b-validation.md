# 0725 Ollama Qwen3.5 4B 연동 검증

- 상태: 검증 완료, 운영 채택 보류
- 결정일: 2026-07-25
- 대상 브랜치: `feat/mvp-api`
- 검증 모델: `hf.co/unsloth/Qwen3.5-4B-GGUF:Q4_K_M`
- 관련 ADR:
  - `0724-llm-risk.md`
  - `0724-mvp-api-completion.md`
  - `0725-upload-scope-check.md`
  - `0725-gemini-gemma4-31b-validation.md`

## 맥락

로컬 Ollama에 설치한 Qwen3.5 4B Q4_K_M 모델이 WorkShield API의
Chat과 Suggestions 구조화 출력 계약을 지킬 수 있는지 확인해야 했다.
이번 검증은 모델이 자연스러운 문장을 생성하는지만 보지 않고 다음
서버 안전 경계를 통과하는지를 기준으로 했다.

- Pydantic 구조화 출력 생성
- 완료된 MCP 검토 스냅샷 안의 사용자·표준조항 ID만 인용
- 조회된 grounding source ID만 인용
- 내부 매칭 점수의 사용자 노출 방지
- Suggestions의 표준조항·법령 출처 누락 또는 변조 차단
- 합법·위법 같은 법률 결론 대신 표준 대비 검토 후보로 표현

## 검증 환경

| 항목 | 값 |
|---|---|
| Ollama 모델 | `hf.co/unsloth/Qwen3.5-4B-GGUF:Q4_K_M` |
| Ollama 표시 크기 | 3.4 GB |
| Ollama endpoint | `http://127.0.0.1:11434` |
| API Python | 3.13.12 |
| LLM reasoning | `OFF` |
| MCP transport | `stdio` |
| MCP SQLite | `mcp/data/migration/contract.sqlite3`, 884,736 bytes |
| Chroma metadata DB | `mcp/data/chroma/chroma.sqlite3`, 9,760,768 bytes |
| 검토 fixture | `01_SW프리랜서용역계약서_기본형.pdf` |

MCP 전체 Review의 재정렬 단계는 현재 `mcp/.env` 설정에 따라 RunPod
API를 사용했다. 따라서 이번 검증은 계약서 파일과 LLM은 로컬이지만
Review 파이프라인 전체가 완전한 offline 구성은 아니다.

## 재현 명령

설치 모델 확인:

```text
ollama list
```

실제 WorkShield MCP BE-A:

```text
cd api
RUN_WORKSHIELD_INTEGRATION=1 \
WORKSHIELD_INTEGRATION_FILE=../mcp/quality/fixtures/track_b/golden_b/raw/01_SW프리랜서용역계약서_기본형.pdf \
WORKSHIELD_MCP_TRANSPORT=stdio \
.venv/bin/pytest -q -m integration \
tests/integration/test_real_workshield_flow.py -k be_a -s
```

실제 WorkShield MCP Review/SSE:

```text
cd api
RUN_WORKSHIELD_REVIEW_INTEGRATION=1 \
WORKSHIELD_INTEGRATION_FILE=../mcp/quality/fixtures/track_b/golden_b/raw/01_SW프리랜서용역계약서_기본형.pdf \
WORKSHIELD_MCP_TRANSPORT=stdio \
WORKSHIELD_REVIEW_WAIT_SECONDS=300 \
.venv/bin/pytest -q -m integration \
tests/integration/test_real_workshield_flow.py -k be_b -s
```

실제 Ollama Chat/Suggestions:

```text
cd api
RUN_LLM_INTEGRATION=1 \
LLM_INTEGRATION_PROVIDER=ollama \
LLM_INTEGRATION_MODEL=hf.co/unsloth/Qwen3.5-4B-GGUF:Q4_K_M \
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
LLM_TEST_TIMEOUT=180 \
.venv/bin/pytest -q -m integration \
tests/integration/test_real_llm_flow.py -s
```

## 결과

### Ollama 기본 구조화 출력

LangChain `ChatOllama.with_structured_output()`으로
`ChatStructuredOutput`을 직접 호출했다.

- 결과: Pydantic DTO 생성 성공
- 최초 모델 로드 포함 응답 시간: 10.53초
- `ANSWERED`, 비어 있지 않은 answer, 허용된 사용자 조항 ID 생성 확인
- 요청한 limitations를 생략한 사례가 있어 선택 필드는 신뢰하지 않기로 함

### 실제 WorkShield MCP

| 테스트 | 결과 | 시간 | 관찰 |
|---|---:|---:|---|
| BE-A metadata·범위 판별·Cookie 격리 | 통과 | 13.10초 | 필수 도구와 저장 자산 정상 |
| BE-B Review·SSE·결과 DTO | 통과 | 99.11초 | 입력 12조항, 표준 코퍼스 23건 |

Chroma 검색과 RunPod 재정렬을 포함한 실제 Review가 `COMPLETED`로
종료됐고 SSE terminal event와 결과 배열 분리를 확인했다.

### 실제 Ollama Chat

최종 실행 결과:

| 항목 | 결과 |
|---|---|
| API outcome | `ANSWERED` |
| 응답 시간 | 11.925초 |
| 사용자 조항 ID | 허용 ID 사용 |
| 표준조항 ID | 허용 ID 사용 |
| 내부 매칭 점수 | 노출하지 않음 |
| 서버 출처 검증 | 통과 |

초기 프롬프트에서는 `ANSWERED`와 함께 `answer=null`을 반환하거나 내부
매칭 점수 `0.95`를 답변에 포함하는 사례가 있었다. 이를 계기로 다음을
보완했다.

- `ANSWERED`의 answer와 sources 필수 조건을 프롬프트에 명시
- LLM 컨텍스트 복사본에서 `match.score` 제거
- 내부 점수·신뢰도·확률을 언급하지 않도록 명시
- 원본 검토 스냅샷은 변경하지 않는 회귀 테스트 추가

최종 구조·출처 검증은 통과했지만, 답변이 `NONE`을 “일치”라고 강하게
표현하는 사례가 있었다. `NONE`은 표준조항 후보가 있다는 뜻이지 동일성,
안전성 또는 적법성 판단이 아니므로 표현 품질 평가는 추가로 필요하다.

### 실제 Ollama Suggestions

최종 실행 결과:

| 항목 | 결과 |
|---|---|
| 모델 원시 outcome | `GENERATED` |
| API outcome | `LLM_OUTPUT_INVALID` |
| 응답 시간 | 3.217초 |
| 문구 생성 | 생성함 |
| `standard_clause_ids` | 빈 배열 |
| `grounding_source_ids` | 빈 배열 |
| 서버 출처 검증 | 누락을 탐지하고 결과 차단 |

충분한 입력과 허용 ID를 프롬프트에 명시한 뒤에도 모델은 세 번의
Suggestions 평가에서 출처 ID를 안정적으로 반환하지 못했다.

- 첫 평가: `LLM_OUTPUT_INVALID`
- 두 번째 평가: 문구는 생성했지만 두 출처 배열이 비어
  `LLM_OUTPUT_INVALID`
- 최종 분리 평가: 같은 출처 누락으로 품질 게이트 실패

서버가 임의 ID를 보충하거나 출처 검증을 완화하지 않았기 때문에 잘못된
Suggestions가 사용자 응답으로 노출되지는 않았다.

### 기본 회귀 테스트

실제 MCP·Ollama opt-in 환경변수를 제외한 기본 검증 결과는 다음과 같다.

```text
Pytest: 166 passed, 4 skipped
Ruff: All checks passed
git diff --check: 통과
```

네 skip은 실제 MCP BE-A·BE-B와 실제 Ollama Chat·Suggestions 테스트다.
기능 누락을 뜻하지 않으며 위 재현 명령으로 각각 명시적으로 실행한다.

## 결정

이 모델을 현재 설정 그대로 운영 기본 모델로 채택하지 않는다.

- Chat: 구조화 출력과 출처 ID 검증은 통과했지만 표현 품질 평가가 더
  필요하므로 개발·실험 용도로만 사용한다.
- Suggestions: 필수 출처 ID 누락이 반복되므로 비활성 상태를 유지한다.
- 서버의 allowlist와 출처 필수 검증은 모델 호환성을 위해 완화하지 않는다.
- `LLM_OUTPUT_INVALID` 안전 실패를 정상적인 차단 동작으로 유지한다.

## 권장 후속 작업

1. 더 큰 Qwen 계열 모델 또는 구조화 출력 준수율이 높은 모델로 같은
   opt-in 테스트를 실행한다.
2. 최소 20개 Chat 질문과 20개 Suggestions 목적을 고정한 평가 fixture로
   성공률, ID 정확도, 금지 표현 발생률과 p50·p95 지연을 측정한다.
3. `NONE`을 동일·안전·적법으로 과장하지 않는 정성 평가 기준을 추가한다.
4. Suggestions의 출처를 서버가 직접 부여하는 설계를 검토한다면,
   모델이 실제 사용한 근거와 서버가 표시한 출처가 달라질 수 있는
   trade-off를 별도 ADR로 합의한다.
5. 완전한 로컬 운영이 목표라면 RunPod 재정렬 의존성을 로컬
   reranker로 교체한 뒤 E2E를 다시 실행한다.

## 보안·해석 원칙

이번 테스트의 MCP 결과와 LLM 답변은 모두 표준 대비 검토 후보와 참고
설명이다. 테스트 통과 여부는 특정 계약의 합법·위법, 유불리 또는 법적
효력을 의미하지 않는다.
