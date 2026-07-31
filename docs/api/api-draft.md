# WorkShield Web API 명세서 v5

> 상태: 프론트엔드·백엔드 구현 협의용 개정안  
> Base URL: `/api/v1`  
> 기준 문서: `mcp-README.md`, `mcp-spec.json`, `01_API_메타데이터_정의서.md`, `요구사항.json`, `운영_정책.json`, `서비스_전체_흐름도.json`, `개발협업용_화면설계서_초안.md`

도메인별 상세 명세:

| 도메인 | 문서 |
|---|---|
| Metadata | [metadata.md](draft-ref/metadata.md) |
| Review sessions | [review-sessions.md](draft-ref/review-sessions.md) |
| Reviews | [reviews.md](draft-ref/reviews.md) |
| Grounding | [grounding.md](draft-ref/grounding.md) |
| Chat | [chat.md](draft-ref/chat.md) |
| Suggestions | [suggestions.md](draft-ref/suggestions.md) |

## 0. 현재 구현 경계

현재 MVP REST API는 metadata, 세션 생성·복구, 계약 유형 확정, 범위 확인, 검토 접수·상태·결과·재시도·SSE, grounding, chat, suggestions, 검토 실행 취소와 결과 폐기까지 구현되어 있다. 멱등 요청은 `idempotency_records`의 scope·세션·요청 fingerprint로 검증하며, chat과 suggestions 응답 스냅샷은 세션 TTL 안에서만 보존한다.

신규 연동은 다음 MCP 도구를 우선 사용한다.

| 목적 | MCP 도구 |
|---|---|
| 계약 범위·유형 후보 판별 | `assess_contract_scope` |
| 전체 계약 검토 | `review_contract_candidates` |
| 계약 유형 목록 | `list_contract_types` |
| 카테고리 목록 | `list_categories` |
| 주의 문구 표시명 | `list_toxic_pattern_details` |
| 카테고리 기반 법령 조회 | `get_category_grounding` |

기존 `review_contract`, `parse_contract`, `classify_clause`, `get_grounding`은 호환 용도로만 사용한다.

---

## 1. API 원칙

- MCP 원본 코드와 애플리케이션 상태를 별도 필드로 유지한다.
- 모든 화면 분기는 `label`이 아니라 `code`로 처리한다.
- `NONE`, `EXTRA`, `NO_MATCH`는 사용자 조항 결과로 관리한다.
- `MISSING`은 `missing_standard_clauses`에 별도 관리한다.
- `toxic_patterns`는 deviation과 독립된 주의 문구 후보이다.
- 매칭 점수와 신뢰도는 MVP 화면에 노출하지 않는다.
- 빈 배열을 안전·정상·문제없음으로 해석하지 않는다.
- 결과와 설명은 법률 자문 또는 위법·합법 판단으로 표현하지 않는다.
- 계약서 원문, 대화 이력, 제안 문구는 영구 저장하지 않는다.
- OpenAI는 현재 사용자 질문의 앞 80자를 분류하는 데만 사용하며, 계약서 원문·조항·검토 결과·대화 이력은 전송하지 않는다. 최종 답변과 제안 문구는 자체 호스팅 vLLM `RedHatAI/Qwen3.5-9B-FP8-dynamic`이 생성한다.
- 외부 LLM으로 답변 생성을 자동 폴백하지 않는다.

---

## 2. API 목록

| 영역 | Method | Path | 설명 | 범위 |
|---|---|---|---|---|
| 메타데이터 | GET | `/api/v1/metadata` | 공통 코드·표시명·파일 정책 | MVP |
| 검토 세션 | POST | `/api/v1/review-sessions` | 파일 업로드·범위 판별 | MVP |
| 검토 세션 | GET | `/api/v1/review-sessions/{session_id}` | 세션 상태 복구 | MVP |
| 검토 세션 | DELETE | `/api/v1/review-sessions/{session_id}` | 업로드 세션·원본 파일 폐기 | MVP |
| 검토 세션 | POST | `/api/v1/review-sessions/{session_id}/extend` | 세션·현재 review·Cookie 만료를 현재부터 30분으로 재설정 | MVP |
| 검토 세션 | PATCH | `/api/v1/review-sessions/{session_id}/contract-type` | 계약 유형 확정 | MVP |
| 검토 세션 | POST | `/api/v1/review-sessions/{session_id}/out-of-scope-confirmation` | 범위 외 계속 진행 확인 | MVP |
| 검토 | POST | `/api/v1/reviews` | 전체 검토 시작 | MVP |
| 검토 | GET | `/api/v1/reviews/{review_id}` | 검토 상태 조회 | MVP |
| 검토 | GET | `/api/v1/reviews/{review_id}/events` | 검토 진행 SSE | MVP |
| 검토 | POST | `/api/v1/reviews/{review_id}/retry` | 재시도 가능한 검토 재실행 | MVP |
| 결과 | GET | `/api/v1/reviews/{review_id}/results` | 전체 결과 조회 | MVP |
| 근거 | GET | `/api/v1/reviews/{review_id}/grounding` | 카테고리 기반 법령 근거 조회 | MVP |
| 챗봇 | POST | `/api/v1/reviews/{review_id}/chat/messages` | 현재 검토 기반 질의응답 | MVP |
| 제안 | POST | `/api/v1/reviews/{review_id}/suggestions` | 단일 협의 문구 생성 | MVP |
| 제안 편집 | PATCH | `/api/v1/reviews/{review_id}/suggestions/{suggestion_id}` | 제안 편집·임시 저장 | MVP 이후 |
| 단일 조항 재검토 | POST | `/api/v1/reviews/{review_id}/clause-reviews` | 수정 문구 단일 조항 재검토 | MVP 이후 |
| 취소 | DELETE | `/api/v1/reviews/{review_id}` | 큐 제거 또는 실행 취소, 결과 폐기·임시 파일 정리 | MVP |

표준조항의 전체 본문·출처·버전은 `review_contract_candidates` 결과에 포함되므로 MVP에서는 별도 표준조항 조회 API를 필수로 두지 않는다.

---

## 3. 공통 응답 계약

### 3.1 성공

```json
{
  "data": {},
  "meta": {
    "request_id": "req_01J...",
    "timestamp": "2026-07-24T09:00:00+09:00"
  }
}
```

### 3.2 오류

```json
{
  "error": {
    "code": "MCP_TIMEOUT",
    "message": "검토 서비스의 응답이 지연되고 있습니다.",
    "field": null,
    "retryable": true,
    "next_action": "RETRY_REVIEW",
    "details": {}
  },
  "meta": {
    "request_id": "req_01J...",
    "timestamp": "2026-07-24T09:00:00+09:00"
  }
}
```

규칙:

- `retryable`은 상태가 아니라 오류의 속성이다.
- `next_action`은 메타데이터의 코드만 사용한다.
- 운영 응답에 서버 경로, 내부 설정, 키, 스택 트레이스, 계약·대화 본문을 포함하지 않는다.
- 권한이 없거나 존재하지 않는 리소스는 동일하게 `404`를 반환할 수 있다.

### 3.3 HTTP 상태

| HTTP | 사용 |
|---:|---|
| `200` | 조회·수정 성공 |
| `201` | 검토 세션 생성 |
| `202` | 비동기 검토 접수 |
| `400` | 요청 형식 오류 |
| `404` | 리소스 없음 또는 접근 불가 |
| `409` | 현재 상태 충돌·중복 실행·멱등성 충돌 |
| `410` | 세션 또는 결과 만료 |
| `413` | 파일 크기 초과 |
| `415` | 미지원 형식 또는 파일 형식 불일치 |
| `422` | 파일 내용·입력·생성 결과 검증 실패 |
| `429` | 요청 빈도 또는 동시성 제한 |
| `502` | MCP·LLM 응답 계약 불일치 |
| `503` | MCP·코퍼스·모델 사용 불가 |
| `504` | 외부 처리 시간 초과 |

### 3.4 멱등성

다음 API는 `Idempotency-Key`를 요구한다.

- `POST /reviews`
- `POST /reviews/{review_id}/retry`
- `POST /reviews/{review_id}/chat/messages`
- `POST /reviews/{review_id}/suggestions`

동일 키와 동일 요청은 기존 응답을 반환한다. 동일 키와 다른 요청은 `409 IDEMPOTENCY_KEY_REUSED`를 반환한다.

---

## 14. 오류 코드

| code | HTTP | retryable | next_action |
|---|---:|---:|---|
| `FILE_EXTENSION_MISSING` | 422 | false | `REUPLOAD` |
| `UNSUPPORTED_FILE_TYPE` | 415 | false | `REUPLOAD` |
| `FILE_TYPE_MISMATCH` | 415 | false | `REUPLOAD` |
| `FILE_TOO_LARGE` | 413 | false | `REUPLOAD` |
| `ENCRYPTED_FILE` | 422 | false | `REUPLOAD` |
| `CORRUPTED_FILE` | 422 | false | `REUPLOAD` |
| `EMPTY_DOCUMENT` | 422 또는 상태 응답 | false | `REUPLOAD` |
| `SESSION_EXPIRED` | 410 | false | `START_NEW_REVIEW` |
| `UNSUPPORTED_CONTRACT_TYPE` | 422 | false | `SELECT_CONTRACT_TYPE` |
| `CONTRACT_TYPE_SELECTION_REQUIRED` | 409 | false | `SELECT_CONTRACT_TYPE` |
| `OUT_OF_SCOPE_CONFIRMATION_REQUIRED` | 409 | false | `CONFIRM_OUT_OF_SCOPE` |
| `REVIEW_ALREADY_RUNNING` | 409 | false | null |
| `REVIEW_NOT_COMPLETED` | 409 | false | null |
| `IDEMPOTENCY_KEY_REUSED` | 409 | false | null |
| `RATE_LIMITED` | 429 | true | null |
| `MCP_TIMEOUT` | 504 | true | `RETRY_REVIEW` |
| `CORPUS_UNAVAILABLE` | 503 | 조건부 | `RETRY_REVIEW` |
| `INVALID_CONFIG` | 503 | false | `CONTACT_SUPPORT` |
| `PIPELINE_ERROR` | 502 | 조건부 | `RETRY_REVIEW` |
| `MCP_RESPONSE_INVALID` | 502 | 조건부 | `CONTACT_SUPPORT` |
| `GROUNDING_TIMEOUT` | 504 | true | `RELOAD_GROUNDING` |
| `GROUNDING_UPSTREAM_ERROR` | 503 | true | `RELOAD_GROUNDING` |
| `CHAT_CONTEXT_INVALID` | 422 | false | null |
| `LLM_OUTPUT_INVALID` | 502 | 조건부 | null |
| `LLM_CITATION_INVALID` | 502 | 조건부 | null |
| `INSUFFICIENT_GROUNDING` | 422 | false | null |
| `REQUIRED_VALUE_MISSING` | 422 | false | null |
| `GENERATED_FACT_NOT_GROUNDED` | 502 | 조건부 | null |
| `INTERNAL_ERROR` | 500 | 조건부 | `CONTACT_SUPPORT` |

`EMPTY_DOCUMENT`는 `POST /review-sessions`에서 세션 상태 응답으로 처리하는 방식을 기본으로 한다. 별도 파일 사전 분석 API에서 세션을 생성하지 않는 경우에만 422 오류로 사용할 수 있다.

---

## 15. 데이터 수명·보안

- 세션 생성 시 최소 256비트의 추측 불가능한 접근 토큰을 발급한다.
- 접근 토큰 원본은 `workshield_session` HttpOnly Cookie로만 전달하고,
  DB에는 SHA-256 해시만 저장한다.
- 세션과 검토 하위 리소스 API는 ID와 Cookie 토큰 해시의 소유권을 함께
  검증한다. Cookie가 없거나 소유권이 다르거나 리소스가 없으면 동일한
  `404 RESOURCE_NOT_FOUND`를 반환한다.
- 소유권 확인 후 세션이 만료된 경우에만 `410 SESSION_EXPIRED`를 반환한다.
- 업로드 파일은 서버가 생성한 임시 경로에 저장한다.
- 사용자 파일명을 저장 경로로 직접 사용하지 않는다.
- 재시도 가능한 실패에서는 세션 TTL까지 원본 파일을 유지할 수 있다.
- 완료된 결과는 사용자가 S05~S08을 사용할 수 있도록 세션 TTL까지 유지한다.
- 세션 만료, 명시적 새 검토, 취소 처리 후 파일·결과·대화를 삭제한다.
- 로컬 stdio 전체 검토는 review별 전용 MCP 세션에서 실행한다. DELETE는 해당 실행 task를 취소하고 전용 세션·자식 프로세스를 닫은 뒤 `CANCELLED` 상태와 파일 정리를 완료한다.
- 비정상 종료 잔존 파일은 서버 시작 또는 정기 정리 작업으로 삭제한다.
- 임시 저장소는 백업 대상에서 제외한다.
- 계약서, 조항, 대화, 프롬프트 본문은 운영 로그와 APM에 기록하지 않는다.
- 외부 구간과 MCP·LLM 연결 구간은 TLS 또는 보안 채널을 사용한다.
- 최종 답변은 자체 호스팅 로컬 모델을 기본으로 사용하며 외부 LLM 답변 생성 자동 폴백을 금지한다. OpenAI 질문 분류와 RunPod 조항 검색·재정렬 경로는 목적과 전송 범위를 분리해 고지한다.

---

## 16. 구현 전 필수 검증

1. 실제 `list_contract_types` 결과와 제품 활성 3개 유형의 일치
2. `assess_contract_scope` 네 상태별 화면 분기
3. candidates 정렬·동점·빈 배열
4. 파일 XOR 입력 계약과 파일 형식 검증
5. `review_contract_candidates`의 null·빈 배열·필수 필드
6. `clause_results`와 `missing_standard_clauses` 분리
7. `match.status`의 `CANDIDATE_SELECTED`·`NO_CANDIDATE`
8. 주의 문구 코드와 메타데이터 표시명 연결
9. MCP progress의 실제 이벤트 필드·순서·오류 형태
10. SSE 연결 끊김 후 상태 조회 복구
11. 법령 조회의 `NO_RESULT`, `UNMAPPED_CATEGORY`, `UPSTREAM_ERROR`, `TIMEOUT`
12. 재시도 가능한 실패의 원본 파일 보존과 TTL 삭제
13. OpenAI router 요청에 현재 질문 앞 80자 외 계약서·조항·검토 결과·대화 이력이 없는지 검증
14. vLLM 답변·제안의 구조화 출력·인용 ID 검증
15. 운영 로그·APM의 계약 본문 미수집

---

## 17. 결정된 MVP 기본값과 미확정 사항

### 17.1 결정된 MVP 기본값

1. 업로드 최대 크기는 10 MiB다.
2. 세션과 결과 TTL은 기본 1,800초다. 일반 API 접근으로 자동 연장하지 않으며 명시적 세션 연장 API만 현재 시각 기준 1,800초로 재설정한다.
3. 인증은 원본 토큰을 응답 본문에 노출하지 않는 익명 HttpOnly Cookie
   소유권 방식이다.
4. API 한 대, 파일형 SQLite와 로컬 FileStorage를 전제로 한다.
5. OpenAI는 현재 사용자 질문 앞 80자의 분류에만 사용하고, 최종 답변의 외부 LLM 자동 fallback은 허용하지 않는다.
6. Chat과 Suggestions는 자체 호스팅 vLLM `RedHatAI/Qwen3.5-9B-FP8-dynamic`의
   구조화 출력·출처 검증을 거친 독립 기능으로 관리하고 MCP 기반
   Review·Grounding과 실패 경로를 분리한다.

### 17.2 미확정 또는 MVP 이후 사항

1. 요청 빈도와 전역 동시 검토 제한
2. SSE 이벤트 영속 보존 범위
3. MCP progress의 실제 `current`, `total` 단위
4. 모델·설정 버전의 수집 방법
5. 사용자 조항의 원문 위치 좌표 제공 여부
6. OpenAI 질문 분류 및 RunPod 조항 검색·재정렬의 전송 범위 고지 방식
7. 협의 문구 목적의 고정 선택지
