# 0727 Suggestions 출처 선택과 백엔드 결정적 결합

- 상태: Accepted
- 결정일: 2026-07-27
- 관련 문서:
  - [0724 LLM 리스크 관리](0724-llm-risk.md)
  - [0725 Ollama Qwen3.5 4B 검증](0725-ollama-qwen35-4b-validation.md)
  - [0725 Gemini Gemma 4 31B 검증](0725-gemini-gemma4-31b-validation.md)
  - [LLM 검증 계획과 기록](../splint/LLM%20검증.md)
  - [0727 RunPod 운영 경계](0727-runpod-shxt.md)

## 1. 배경

기존 Suggestions 구조화 출력은 LLM이 실제
`standard_clause_ids`와 `grounding_source_ids`를 입력에서 찾아 그대로
복사하도록 요구했다.

Ollama Qwen3.5 4B 검증에서는 제안 문구를 생성하고도 두 출처 배열을
비워 서버 검증에서 차단됐다. Gemini Gemma 4 31B는 같은 단일 합성
fixture에서 ID를 반환했지만 모델 크기, provider, 원격 인프라가 함께
달랐기 때문에 모델 자체의 문구 생성 품질 차이로 해석할 수 없었다.

실제 출처 ID는 이미 MCP와 백엔드가 현재 Review·Grounding 결과에서
확정한 값이다. 모델에 이 값을 다시 생성하게 하면 다음과 같이 LLM의
본래 역할과 무관한 실패가 발생한다.

- 정확한 긴 문자열 복사 실패
- 존재하지 않는 ID 생성
- 다른 세션 ID 혼입
- 문구는 유효하지만 ID 누락 때문에 전체 결과 차단
- 모델 크기와 출처 복사 능력을 혼동한 품질 평가

## 2. 결정

Suggestions에서 실제 출처 ID의 정확성과 세션 소유권은 백엔드가
책임진다. LLM은 어떤 종류의 검증된 입력 근거를 사용했는지만 선택한다.

### 2.1 LLM 입력

백엔드는 Suggestions 모델 컨텍스트에서 다음 실제 식별자를 제거한다.

- canonical `user_clause_id`
- MCP 표준조항 `clause_id`
- Grounding `source_id`

사용자 조항, 표준조항, 법령 참고 원문의 본문과 필요한 메타데이터는
읽기 전용 계약 데이터로 제공한다.

### 2.2 LLM 출력

LLM은 provider 공통 Pydantic·JSON Schema에 따라 다음 값을 생성한다.

```json
{
  "outcome": "GENERATED",
  "suggestion": "제안 문구",
  "major_changes": ["주요 변경사항"],
  "used_source_keys": [
    "SRC_USER",
    "SRC_STANDARD",
    "SRC_GROUNDING"
  ],
  "required_confirmations": []
}
```

허용 source key는 다음의 닫힌 집합뿐이다.

- `SRC_USER`: 대상 사용자 조항
- `SRC_STANDARD`: MCP가 선택한 대응 표준조항
- `SRC_GROUNDING`: 이번 요청에서 조회한 법령 참고 원문

### 2.3 백엔드 결합

백엔드는 모델이 선택한 source key를 현재 요청의 검증된 값에
결정적으로 결합한다.

| source key | API 응답에 결합하는 값 |
| --- | --- |
| `SRC_USER` | 요청 대상 canonical `user_clause_id` |
| `SRC_STANDARD` | 현재 Review의 `standard.clause_id` |
| `SRC_GROUNDING` | 이번 Grounding 응답의 `source_id` 목록 |

API 응답의 `user_clause_ids`, `standard_clause_ids`,
`grounding_source_ids`는 LLM이 생성한 인용이 아니다. 백엔드가 현재
세션의 검증된 입력에 연결한 출처다. `used_source_keys`는 모델이 문구
작성에 사용했다고 선택한 근거 종류를 나타낸다.

이 결정은 Ollama, Gemini, OpenAI-compatible, vLLM 등 모든 provider에
동일하게 적용한다. provider별 클라이언트가 아니라 Suggestions
스키마와 서비스 계층의 계약이기 때문이다.

Chat은 기존과 같이 `sources[].type`과 `sources[].id`를 반환하고 서버
allowlist 검증을 수행한다. 이번 결정은 Suggestions에만 적용한다.

## 3. 검증

다음 회귀 테스트로 현재 구현을 확인했다.

```text
cd api
.venv/bin/pytest -q \
  tests/domains/suggestions/test_schemas.py \
  tests/domains/suggestions/test_service.py
```

결과는 `6 passed`다.

- `GENERATED`에서 하나 이상의 닫힌 source key를 요구한다.
- 스키마 밖 source key를 거부한다.
- 실제 사용자·표준조항·Grounding ID를 LLM 프롬프트에 포함하지 않는다.
- 선택된 source key에 해당하는 ID만 API 응답에 결합한다.

이 테스트는 백엔드 계약 검증이며 실제 후보 모델의 품질 승인을 뜻하지
않는다.

## 4. 결과

### 긍정적 결과

- 작은 모델의 문자열 복사 능력과 제안 문구 품질을 분리할 수 있다.
- 존재하지 않거나 다른 세션의 출처 ID를 모델이 주입할 수 없다.
- 모델 교체 시에도 동일한 Suggestions 출력 계약을 유지한다.
- 출처 ID 정확성을 결정론적으로 보장하고 모델은 근거 선택에 집중한다.
- Qwen3.5 9B 같은 비용 효율적인 모델을 우선 평가할 수 있다.

### 비용과 한계

- 백엔드에 모델 컨텍스트 정제와 source key 결합 로직이 필요하다.
- 모델이 필요한 근거 종류를 누락하거나 과다 선택할 가능성은 남는다.
- 현재 `SRC_GROUNDING`은 항목 단위가 아니라 Grounding 종류 단위다.
  선택하면 이번 요청에서 조회한 `source_id` 목록 전체가 결합되므로,
  모델이 실제로 사용한 법령 항목 하나까지 식별하지는 못한다.
- 반환된 ID는 “모델이 이 ID 문자열을 직접 인용했다”는 의미가 아니라
  “모델이 선택한 근거 종류에 백엔드가 연결한 검증된 출처”라는 의미다.

## 5. 검토한 대안

### 5.1 LLM이 실제 ID를 계속 복사

채택하지 않았다. 의미 생성과 무관한 문자열 복사 실패가 모델 품질과
안전성 평가를 왜곡하고, 작은 모델의 불필요한 실패 원인이 된다.

### 5.2 모델 선택과 무관하게 모든 출처 ID를 항상 표시

채택하지 않았다. 문구에 사용하지 않은 근거 종류까지 사용한 것처럼
표시할 수 있다. LLM이 선택한 근거 종류와 백엔드가 결합한 실제 ID를
함께 반환한다.

### 5.3 요청별 항목 단위 opaque key 제공

현재는 채택하지 않았다. `SRC_GROUNDING_1`처럼 실제 ID가 아닌 요청별
키를 사용하면 항목 단위 provenance를 표현할 수 있지만 스키마와
프롬프트 복잡도가 증가한다. 항목 단위 출처 정밀도가 제품 요구사항이
되면 도입을 재검토한다.

## 6. 재검토 조건

다음 상황에서 이 결정을 다시 검토한다.

- 법령 참고자료를 항목 단위로 정확히 연결해야 함
- 하나의 제안이 여러 사용자 조항이나 표준조항을 사용함
- source key 누락·과다 선택이 운영 품질 기준을 충족하지 못함
- 사용자에게 표시하는 출처의 의미를 직접 인용으로 강화해야 함

## 7. 결정 범위

이 ADR은 Suggestions의 출처 책임과 결합 방식만 결정한다. RunPod
Pod·Serverless 사용 경계, 인증, 배포 방식은
`0727-runpod-shxt.md`를 따른다. 운영 모델, 양자화와 vLLM provider
채택은 별도 검증 후 확정한다.
