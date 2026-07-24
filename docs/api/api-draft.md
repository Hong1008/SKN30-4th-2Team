# WorkShield Web API 명세서 v5

> 상태: 프론트엔드·백엔드 구현 협의용 개정안  
> Base URL: `/api/v1`  
> 기준 문서: `mcp-README.md`, `mcp-spec.json`, `01_API_메타데이터_정의서.md`, `요구사항.json`, `운영_정책.json`, `서비스_전체_흐름도.json`, `개발협업용_화면설계서_초안.md`

## 0. 현재 구현 경계

현재 확인된 프로젝트 소스는 **MCP 서버와 MCP 도구 계약**이다. 이 문서의 REST API는 웹 애플리케이션 백엔드가 MCP를 감싸기 위한 목표 계약이며, 구현 완료 상태를 의미하지 않는다.

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
- 외부 LLM으로 자동 폴백하지 않는다.

---

## 2. API 목록

| 영역 | Method | Path | 설명 | 범위 |
|---|---|---|---|---|
| 메타데이터 | GET | `/api/v1/metadata` | 공통 코드·표시명·파일 정책 | MVP |
| 검토 세션 | POST | `/api/v1/review-sessions` | 파일 업로드·범위 판별 | MVP |
| 검토 세션 | GET | `/api/v1/review-sessions/{session_id}` | 세션 상태 복구 | MVP |
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
| 취소 | DELETE | `/api/v1/reviews/{review_id}` | 검토 작업 취소 | MVP 이후 |

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

## 4. 메타데이터

### 4.1 `GET /api/v1/metadata`

프론트엔드는 계약 유형, 카테고리, 상태, 오류 코드를 하드코딩하지 않는다.

응답:

```json
{
  "data": {
    "schema_version": "1.1",
    "updated_at": "2026-07-24T09:00:00+09:00",
    "contract_types": [
      {
        "code": "SW_FREELANCE",
        "label": "SW 프리랜서 용역",
        "description": "SW 프리랜서 도급·용역 계약 비교 기준입니다.",
        "enabled_for_mvp": true
      },
      {
        "code": "SI_SUBCONTRACT",
        "label": "SI 하도급",
        "description": "SI 구축 하도급 계약 비교 기준입니다.",
        "enabled_for_mvp": true
      },
      {
        "code": "SM_SUBCONTRACT",
        "label": "SM 하도급",
        "description": "SM 운영·유지보수 하도급 계약 비교 기준입니다.",
        "enabled_for_mvp": true
      },
      {
        "code": "SW_EMPLOYMENT",
        "label": "SW 근로계약",
        "description": "MCP가 지원하지만 현재 제품 MVP 선택 목록에서는 비활성화합니다.",
        "enabled_for_mvp": false
      }
    ],
    "categories": [],
    "toxic_patterns": [],
    "scope_statuses": [],
    "review_states": [],
    "result_codes": [],
    "progress_stages": [],
    "grounding_statuses": [],
    "chat_outcomes": [],
    "draft_outcomes": [],
    "error_codes": [],
    "selection_sources": [],
    "next_actions": [],
    "file_policy": {
      "extensions": ["hwp", "hwpx", "hwpml", "pdf", "xls", "xlsx", "docx"],
      "max_size_bytes": 20971520,
      "single_file_only": true,
      "encrypted_file_allowed": false
    },
    "features": {
      "chat": true,
      "basic_suggestion": true,
      "confidence_score": false,
      "suggestion_edit": false,
      "single_clause_rereview": false,
      "server_side_cancel": false
    }
  }
}
```

계약 유형 원본 목록은 MCP `list_contract_types`를 기준으로 검증한다. 제품 MVP에서는 `enabled_for_mvp=true`인 세 유형만 선택할 수 있다.

### 4.2 캐시

백엔드는 MCP의 계약 유형·카테고리·주의 문구 메타데이터를 5~10분 캐시한다.

권장 헤더:

```http
Cache-Control: public, max-age=300, stale-while-revalidate=600
ETag: "metadata-1.1-20260724"
```

프론트는 요청 라이브러리의 메모리 캐시를 사용한다. MVP에서는 `localStorage` 영속 캐시를 사용하지 않는다.

### 4.3 메타데이터 코드

#### 범위 판별 상태

```text
IN_SCOPE
CONTRACT_TYPE_UNCERTAIN
OUT_OF_SCOPE
EMPTY_DOCUMENT
```

#### 검토 세션 상태

```text
TYPE_ANALYZING
TYPE_SELECTION_REQUIRED
OUT_OF_SCOPE_CONFIRMATION_REQUIRED
READY_TO_REVIEW
QUEUED
REVIEWING
COMPLETED
REUPLOAD_REQUIRED
FAILED
EXPIRED
```

#### 결과 코드

```text
NONE
EXTRA
NO_MATCH
MISSING
```

`MISSING`의 `group`은 `STANDARD_CHECKLIST`, 나머지는 `CLAUSE_RESULT`이다.

#### 진행 단계

```text
PREPARE
BATCH_SEARCH
RERANK
CLAUSE_REVIEW
MISSING_DETECTION
RESULT_ASSEMBLY
```

#### 법령 조회 상태

```text
OK
NO_RESULT
UNMAPPED_CATEGORY
UPSTREAM_ERROR
TIMEOUT
```

#### 선택 경로

```text
SUGGESTED
CANDIDATE
MANUAL
```

#### 다음 행동

```text
REUPLOAD
RETRY_SCOPE_ANALYSIS
SELECT_CONTRACT_TYPE
CONFIRM_OUT_OF_SCOPE
RETRY_REVIEW
RELOAD_GROUNDING
START_NEW_REVIEW
CONTACT_SUPPORT
```

---

## 5. 파일 업로드·범위 판별

### 5.1 `POST /api/v1/review-sessions`

Content-Type: `multipart/form-data`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `file` | binary | Y | 계약서 파일 |

자체 호스팅 LLM을 기본 사용하므로 업로드 요청에 외부 LLM 동의 필드를 포함하지 않는다. 외부 LLM 사용 기능을 추가할 경우 공급자·목적·전송 범위·정책 버전을 포함한 별도 동의 계약을 정의한다.

검증 순서:

1. 파일명과 확장자
2. 지원 확장자
3. 최대 파일 크기
4. 확장자와 실제 파일 형식
5. 암호화·손상 여부
6. 서버 생성 임시 경로
7. MCP 입력 XOR 계약
8. `assess_contract_scope`

MCP 입력은 다음 중 하나만 허용한다.

```text
file_path
또는
file_content + file_name
```

### 5.2 정상 범위 판별 응답

성공 `201`:

```json
{
  "data": {
    "session_id": "ses_01J...",
    "review_state": "TYPE_SELECTION_REQUIRED",
    "upload": {
      "file_name": "계약서.pdf",
      "size_bytes": 421398,
      "extension": "pdf"
    },
    "scope_status": "CONTRACT_TYPE_UNCERTAIN",
    "scope_message": "계약 유형을 선택해 주세요.",
    "suggested_contract_type": "SW_FREELANCE",
    "selected_contract_type": null,
    "selection_source": null,
    "candidates": [
      {
        "contract_type": "SW_FREELANCE",
        "evidence_score": 82
      }
    ],
    "matched_clause_count": 8,
    "allowed_actions": ["SELECT_CONTRACT_TYPE"],
    "expires_at": "2026-07-24T10:00:00+09:00"
  }
}
```

`evidence_score`는 MCP의 결정론적 근거 점수를 보존한 값이며 확률·신뢰도·법률 판단이 아니다. MVP 화면에는 숫자를 노출하지 않는다.

### 5.3 빈 문서 응답

확장자·실제 형식 검증은 통과했으나 MCP가 `EMPTY_DOCUMENT`를 반환한 경우 세션을 생성하고 재업로드 상태를 반환한다.

```json
{
  "data": {
    "session_id": "ses_01J...",
    "review_state": "REUPLOAD_REQUIRED",
    "scope_status": "EMPTY_DOCUMENT",
    "scope_message": "검토 가능한 조항을 추출하지 못했습니다.",
    "allowed_actions": ["REUPLOAD"],
    "expires_at": "2026-07-24T10:00:00+09:00"
  }
}
```

이 상태에서는 `POST /reviews`를 허용하지 않는다.

### 5.4 업로드 오류

| 오류 코드 | HTTP |
|---|---:|
| `FILE_EXTENSION_MISSING` | 422 |
| `UNSUPPORTED_FILE_TYPE` | 415 |
| `FILE_TYPE_MISMATCH` | 415 |
| `FILE_TOO_LARGE` | 413 |
| `ENCRYPTED_FILE` | 422 |
| `CORRUPTED_FILE` | 422 |
| `UPLOAD_FAILED` | 500 |

---

## 6. 계약 유형 확정

### 6.1 `PATCH /api/v1/review-sessions/{session_id}/contract-type`

```json
{
  "selected_contract_type": "SW_FREELANCE",
  "selection_source": "SUGGESTED"
}
```

검증:

- 메타데이터의 `enabled_for_mvp=true` 유형만 허용한다.
- 추천 유형과 사용자 선택 유형을 별도 저장한다.
- `CONTRACT_TYPE_UNCERTAIN`에서도 사용자가 선택하면 진행할 수 있다.
- `OUT_OF_SCOPE`는 계약 유형 선택만으로 진행할 수 없으며 계속 진행 확인이 필요하다.

응답:

```json
{
  "data": {
    "session_id": "ses_01J...",
    "scope_status": "IN_SCOPE",
    "suggested_contract_type": "SW_FREELANCE",
    "selected_contract_type": "SW_FREELANCE",
    "selection_source": "SUGGESTED",
    "review_state": "READY_TO_REVIEW",
    "can_start_review": true
  }
}
```

### 6.2 `POST /api/v1/review-sessions/{session_id}/out-of-scope-confirmation`

```json
{
  "confirmed": true
}
```

응답:

```json
{
  "data": {
    "session_id": "ses_01J...",
    "scope_status": "OUT_OF_SCOPE",
    "out_of_scope_confirmed_at": "2026-07-24T09:10:00+09:00",
    "review_state": "READY_TO_REVIEW",
    "can_start_review": true
  }
}
```

`selected_contract_type`이 없으면 확인 후에도 `can_start_review=false`이다.

---

## 7. 검토 시작·상태 조회

### 7.1 `POST /api/v1/reviews`

요청:

```json
{
  "session_id": "ses_01J..."
}
```

성공 `202`:

```json
{
  "data": {
    "review_id": "rev_01J...",
    "review_state": "QUEUED",
    "mcp_review_status": null,
    "snapshot": {
      "contract_type": "SW_FREELANCE",
      "standard_clause_versions": [],
      "model_version": null,
      "settings_version": null
    },
    "progress": {
      "sequence": 0,
      "stage": "PREPARE",
      "current": 0,
      "total": null,
      "percent": 0,
      "message": "검토를 준비하고 있습니다."
    },
    "links": {
      "events": "/api/v1/reviews/rev_01J.../events",
      "status": "/api/v1/reviews/rev_01J...",
      "results": "/api/v1/reviews/rev_01J.../results"
    }
  }
}
```

검토 시작 조건:

- `selected_contract_type` 존재
- 선택 유형이 MVP 활성 유형
- `scope_status != EMPTY_DOCUMENT`
- `scope_status != OUT_OF_SCOPE` 또는 계속 진행 확인 완료
- 세션 미만료
- 동일 세션의 실행 중 검토 없음

### 7.2 상태 코드

애플리케이션 `review_state`:

```text
QUEUED
REVIEWING
COMPLETED
FAILED
EXPIRED
```

MCP `mcp_review_status`:

```text
null
OK
EMPTY_DOCUMENT
CORPUS_UNAVAILABLE
INVALID_CONFIG
PIPELINE_ERROR
```

초기·실행 중에는 `mcp_review_status=null`이다. `PENDING`은 MCP 원본 상태로 사용하지 않는다.

### 7.3 `GET /api/v1/reviews/{review_id}`

```json
{
  "data": {
    "review_id": "rev_01J...",
    "review_state": "REVIEWING",
    "mcp_review_status": null,
    "progress": {
      "sequence": 17,
      "stage": "CLAUSE_REVIEW",
      "current": 7,
      "total": 17,
      "percent": 41,
      "message": "계약 조항을 비교하고 있습니다."
    },
    "error": null,
    "started_at": "2026-07-24T09:11:00+09:00",
    "completed_at": null,
    "expires_at": "2026-07-24T10:00:00+09:00"
  }
}
```

---

## 8. SSE 진행 이벤트

### 8.1 `GET /api/v1/reviews/{review_id}/events`

이벤트:

```text
progress
completed
failed
resync_required
```

예시:

```text
id: 17
event: progress
data: {"review_id":"rev_01J...","sequence":17,"review_state":"REVIEWING","stage":"CLAUSE_REVIEW","current":7,"total":17,"percent":41,"message":"계약 조항을 비교하고 있습니다."}
```

규칙:

- MCP의 실제 progress를 `review_id`와 연결한다.
- `sequence`가 이전 값 이하인 이벤트는 폐기한다.
- 진행률은 서버에서 역행하지 않게 정규화한다.
- `current`와 `total`이 있으면 `percent=floor(current/total*100)`을 기본값으로 사용한다.
- 단계 가중치 방식으로 변경할 경우 계산 규칙을 별도 버전으로 고정한다.
- 완료·실패 이벤트 후 진행 표시를 종료한다.
- SSE 연결이 끊기면 `GET /reviews/{review_id}`로 상태를 동기화한 뒤 재연결한다.
- 이벤트 영속 보존을 구현하지 않는 MVP에서는 `Last-Event-ID` 완전 복구를 보장하지 않는다.

완료 예시:

```text
event: completed
data: {"review_id":"rev_01J...","sequence":24,"review_state":"COMPLETED","mcp_review_status":"OK"}
```

실패 예시:

```text
event: failed
data: {"review_id":"rev_01J...","sequence":24,"review_state":"FAILED","mcp_review_status":"PIPELINE_ERROR","error":{"code":"PIPELINE_ERROR","retryable":true,"next_action":"RETRY_REVIEW"}}
```

---

## 9. 재시도

### 9.1 `POST /api/v1/reviews/{review_id}/retry`

조건:

- 이전 검토가 `FAILED`
- 오류의 `retryable=true`
- 원본 세션과 임시 파일이 만료되지 않음
- 동일 재시도 요청이 실행 중이 아님

응답은 새 `review_id`를 반환한다.

```json
{
  "data": {
    "review_id": "rev_01K...",
    "retry_of": "rev_01J...",
    "review_state": "QUEUED"
  }
}
```

재시도 가능한 실패에서는 원본 파일을 세션 TTL까지 보존한다. TTL 만료 또는 재시도 불가능 실패에서는 재업로드가 필요하다.

---

## 10. 검토 결과

### 10.1 `GET /api/v1/reviews/{review_id}/results`

MVP에서는 검토 결과 전체를 한 번에 반환하고 상태·카테고리·키워드 필터를 프론트에서 처리한다.

```json
{
  "data": {
    "review": {
      "review_id": "rev_01J...",
      "review_state": "COMPLETED",
      "mcp_review_status": "OK",
      "contract_type": "SW_FREELANCE",
      "started_at": "2026-07-24T09:11:00+09:00",
      "completed_at": "2026-07-24T09:13:00+09:00",
      "expires_at": "2026-07-24T10:00:00+09:00",
      "disclaimer": "표준계약서 대비 검토 후보이며 법률 자문이 아닙니다."
    },
    "summary": {
      "clause_results": {
        "total": 17,
        "NONE": 10,
        "EXTRA": 4,
        "NO_MATCH": 3
      },
      "missing_standard_clauses": 2,
      "toxic_pattern_candidates": 3
    },
    "clause_results": [],
    "missing_standard_clauses": []
  }
}
```

### 10.2 사용자 조항 결과

백엔드는 MCP 결과 순서로 `user_clause_id`를 생성한다.

```text
user_clause_id = "uc_" + review_id + "_" + 1부터 시작하는 결과 순번
```

응답 예시:

```json
{
  "user_clause_id": "uc_rev_01J_7",
  "user_clause": "제7조(손해배상) ...",
  "deviation": {
    "code": "EXTRA",
    "label": "추가·변형 내용 확인"
  },
  "match": {
    "status": "CANDIDATE_SELECTED",
    "standard": {
      "clause_id": "sw_freelance-2020-art12",
      "contract_type": "SW_FREELANCE",
      "category": {
        "code": "LIABILITY",
        "label": "책임·손해배상"
      },
      "title": "손해배상",
      "text": "...",
      "source": "...",
      "version": "2020"
    }
  },
  "explanation": "표준조항 후보는 있으나 대응 기준에 미치지 못해 추가 확인이 필요한 조항입니다.",
  "toxic_patterns": [
    {
      "code": "UNFAIR_DAMAGE_CLAIM",
      "label": "과도한 손해배상 표현"
    }
  ]
}
```

`explanation`은 LLM 자유 생성이 아니라 deviation별 서버 고정 설명을 기본으로 한다.

MCP가 제공하지 않는 다음 값은 MVP 응답에 포함하지 않는다.

- 페이지 번호
- 원문 좌표
- 패턴별 탐지 이유
- LLM 비교 사유
- 신뢰도·점수

`match.status=NO_CANDIDATE`이면 `standard` 필드를 포함하지 않는다.

### 10.3 MISSING 체크리스트

```json
{
  "result_type": {
    "code": "MISSING",
    "label": "포함 여부 확인"
  },
  "standard": {
    "clause_id": "sw_freelance-2020-art1",
    "contract_type": "SW_FREELANCE",
    "category": {
      "code": "GENERAL",
      "label": "일반 조항"
    },
    "title": "기본원칙",
    "text": "...",
    "source": "...",
    "version": "2020"
  },
  "explanation": "이 표준조항에 대응하는 내용을 계약서 전체에서 찾지 못해 포함 여부 확인이 필요합니다."
}
```

MISSING 응답에는 사용자 조항, 매칭 점수, `match`를 만들지 않는다.

### 10.4 결과 규칙

- 최상위 `mcp_review_status`를 배열보다 먼저 확인한다.
- `mcp_review_status != OK`이면 결과 배열을 표시하지 않는다.
- `toxic_patterns=[]`는 안전함을 뜻하지 않는다.
- 요약 수치와 결과 배열은 동일한 스냅샷에서 계산한다.
- 알 수 없는 MCP enum은 임의 라벨로 정상 처리하지 않고 `502 MCP_RESPONSE_INVALID`로 처리한다.

---

## 11. 법령 근거

### 11.1 `GET /api/v1/reviews/{review_id}/grounding`

Query:

```text
category={category_code}
```

백엔드는 검토 스냅샷의 `contract_type`과 요청의 `category`로 `get_category_grounding`을 호출한다.

응답:

```json
{
  "data": {
    "grounding_status": "OK",
    "category": {
      "code": "LIABILITY",
      "label": "책임·손해배상"
    },
    "contract_type": "SW_FREELANCE",
    "items": [
      {
        "source_id": "law_1",
        "law_name": "민법",
        "article": "제390조",
        "text": "...",
        "source": "국가법령정보센터 또는 출처 좌표",
        "source_url": null
      }
    ],
    "message": null
  }
}
```

정상 빈 결과:

```json
{
  "data": {
    "grounding_status": "NO_RESULT",
    "category": {
      "code": "LIABILITY",
      "label": "책임·손해배상"
    },
    "contract_type": "SW_FREELANCE",
    "items": [],
    "message": "조회된 관련 법령 자료가 없습니다."
  }
}
```

규칙:

- `NO_RESULT`, `UNMAPPED_CATEGORY`는 HTTP 오류가 아닌 정상 응답이다.
- `UPSTREAM_ERROR`, `TIMEOUT`은 오류 응답 또는 동일 구조의 실패 상태로 정규화할 수 있으나 한 방식을 일관되게 사용한다.
- MCP의 `출처`는 URL이라고 보장되지 않으므로 `source`에 보존한다.
- URL 형식으로 검증된 경우에만 `source_url`을 제공한다.
- 법령 조회 실패가 전체 검토 상태를 `FAILED`로 변경하지 않는다.

---

## 12. 챗봇

### 12.1 `POST /api/v1/reviews/{review_id}/chat/messages`

요청:

```json
{
  "message": "제7조에서 확인할 부분을 설명해 줘.",
  "focus_clause_id": "uc_rev_01J_7",
  "history": []
}
```

클라이언트가 표준조항 ID와 법령 ID를 임의로 조합하지 않는다. 백엔드는 `focus_clause_id`를 기준으로 현재 세션의 근거를 조회한다.

응답:

```json
{
  "data": {
    "outcome": "ANSWERED",
    "answer": "해당 조항은 대응 표준조항 후보와 비교했을 때 추가 확인이 필요한 표현을 포함합니다.",
    "refused": false,
    "sources": [
      {
        "type": "USER_CLAUSE",
        "id": "uc_rev_01J_7"
      },
      {
        "type": "STANDARD_CLAUSE",
        "id": "sw_freelance-2020-art12"
      },
      {
        "type": "LAW",
        "law_name": "민법",
        "article": "제390조"
      }
    ],
    "limitations": [
      "법률적 유효성이나 유불리를 확정하지 않습니다."
    ],
    "tool_status": "OK",
    "disclaimer": "현재 검토 결과와 확인된 근거에 한정한 참고 설명입니다."
  }
}
```

거절 응답:

```json
{
  "data": {
    "outcome": "REFUSED",
    "answer": null,
    "refused": true,
    "sources": [],
    "limitations": [
      "현재 검토 결과에서 질문을 뒷받침할 근거를 찾지 못했습니다."
    ],
    "tool_status": "OK"
  }
}
```

규칙:

- 현재 계약서, 검토 결과, 조회된 법령 근거만 사용한다.
- 인용 ID가 현재 세션에 존재하는지 백엔드에서 검증한다.
- 문서 원문의 명령문을 시스템 명령으로 실행하지 않는다.
- 구조화 출력 검증에 실패하면 답변을 표시하지 않는다.
- MCP 실패 시 추측 답변을 생성하지 않는다.
- 대화 이력은 브라우저 메모리 또는 제한된 세션 범위에서만 유지한다.

---

## 13. 협의 문구

### 13.1 `POST /api/v1/reviews/{review_id}/suggestions`

요청:

```json
{
  "user_clause_id": "uc_rev_01J_7",
  "purpose": "책임 범위를 명확히 하기 위한 협의 문구"
}
```

생성 조건:

```text
사용자 조항 존재
AND match.status == CANDIDATE_SELECTED
AND match.standard 존재
```

`NO_MATCH`, `MISSING`, `NO_CANDIDATE`는 기본 생성 대상에서 제외한다.

성공:

```json
{
  "data": {
    "outcome": "GENERATED",
    "text": "손해배상 책임의 범위와 한도는 [금액 확인 필요]로 협의한다.",
    "purpose": "책임 범위를 명확히 하기 위한 협의 문구",
    "key_changes": [
      "책임 한도 확인 항목 추가"
    ],
    "standard_clause_ids": [
      "sw_freelance-2020-art12"
    ],
    "required_confirmations": [
      {
        "field": "liability_limit",
        "placeholder": "[금액 확인 필요]"
      }
    ],
    "disclaimer": "자동 반영되지 않는 협의용 참고 초안이며 법률 자문이 아닙니다."
  }
}
```

근거 부족:

```json
{
  "data": {
    "outcome": "INSUFFICIENT_GROUNDING",
    "text": null,
    "missing_inputs": [
      "대응 표준조항"
    ]
  }
}
```

MVP에서는 제안 문구를 서버 리소스로 영구 저장하지 않으므로 `suggestion_id`를 필수로 두지 않는다.

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

- 업로드 파일은 서버가 생성한 임시 경로에 저장한다.
- 사용자 파일명을 저장 경로로 직접 사용하지 않는다.
- 재시도 가능한 실패에서는 세션 TTL까지 원본 파일을 유지할 수 있다.
- 완료된 결과는 사용자가 S05~S08을 사용할 수 있도록 세션 TTL까지 유지한다.
- 세션 만료, 명시적 새 검토, 취소 처리 후 파일·결과·대화를 삭제한다.
- 비정상 종료 잔존 파일은 서버 시작 또는 정기 정리 작업으로 삭제한다.
- 임시 저장소는 백업 대상에서 제외한다.
- 계약서, 조항, 대화, 프롬프트 본문은 운영 로그와 APM에 기록하지 않는다.
- 외부 구간과 MCP·LLM 연결 구간은 TLS 또는 보안 채널을 사용한다.
- 자체 호스팅 LLM을 기본으로 사용하며 외부 LLM 자동 폴백을 금지한다.

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
13. LLM 구조화 출력·인용 ID 검증
14. 운영 로그·APM의 계약 본문 미수집

---

## 17. 미확정 사항

1. 실제 최대 파일 크기
2. 세션·결과 TTL
3. 요청 빈도와 동시 검토 제한
4. 인증 방식
5. SSE 이벤트 보존 범위
6. MCP progress의 실제 `current`, `total` 단위
7. 모델·설정 버전의 수집 방법
8. 사용자 조항의 원문 위치 좌표 제공 여부
9. 외부 LLM 동의 기능의 도입 여부
10. 협의 문구 목적의 고정 선택지
