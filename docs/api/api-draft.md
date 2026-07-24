# WorkShield API 명세서 v1

>
> - **v1**: `요구사항.json`만 기준으로 작성한 **공식 검토용 문서**입니다. API 범위와 구조, 상태, 오류 정책을 확인할 때 우선 참고해 주세요.

> - 아직 확정되지 않은 제한값, 인증 방식, TTL 등은 화면·배포 설계 협의 후 최종 확정할 예정입니다.

> 상태: 프론트엔드·백엔드 협의용 초안  
> 단일 근거: `docs/requirements/요구사항.json`  
> 요구사항: 75개(MVP 67개, MVP 이후 8개)  
> Base URL 제안: `/api/v1`

## 1. 범위와 원칙

이 문서는 요구사항 JSON만을 근거로 작성했다.

- 기존 API 초안, 엑셀, 현재 구현 코드는 내용 근거로 사용하지 않는다.
- JSON에서 확정하지 않은 제한값과 운영값은 `미정`으로 둔다.
- MCP 원본 응답은 백엔드가 검증·정규화한 후 프론트에 제공한다.
- 결과는 표준계약서 대비 검토 후보이며 법률 자문이나 법적 결론이 아니다.
- 원본 상태 코드와 사용자 표시명을 별도 필드로 유지한다.

## 2. 사용자 흐름

```text
설정·지원 유형 조회
  → 계약서 업로드
  → 계약 유형 후보 판별
  → 사용자가 최종 유형 확정
  → OUT_OF_SCOPE이면 계속 진행 재확인
  → 비동기 검토 시작
  → SSE 또는 폴링으로 진행 표시
  → 결과·MISSING·주의 문구 확인
  → 표준조항·법령 근거 조회
  → 근거 기반 챗봇·협의 문구
  → 완료·실패·만료 후 임시 데이터 삭제
```

검토 시작 차단 조건:

- 지원하지 않는 파일
- 확장자와 실제 형식 불일치
- 암호화·손상·빈 문서
- 파일 크기 초과
- 계약 유형 미선택
- `OUT_OF_SCOPE` 재확인 미완료
- 세션 만료 또는 검토 중복 실행

## 3. API 목록

| 영역 | Method | Path | 설명 | 범위 |
| --- | --- | --- | --- | --- |
| 설정 | GET | `/api/v1/config` | 제한값·기능 플래그 | MVP |
| 메타 | GET | `/api/v1/contract-types` | 지원 계약 유형 | MVP |
| 메타 | GET | `/api/v1/categories` | 결과 카테고리 | MVP |
| 메타 | GET | `/api/v1/toxic-patterns` | 주의 문구 표시명 | MVP |
| 세션 | POST | `/api/v1/review-sessions` | 업로드·유형 판별 | MVP |
| 세션 | GET | `/api/v1/review-sessions/{session_id}` | 세션 상태 복구 | MVP |
| 세션 | PATCH | `/api/v1/review-sessions/{session_id}/contract-type` | 유형 확정 | MVP |
| 검토 | POST | `/api/v1/reviews` | 전체 검토 시작 | MVP |
| 검토 | GET | `/api/v1/reviews/{review_id}` | 상태 조회·폴링 | MVP |
| 검토 | GET | `/api/v1/reviews/{review_id}/events` | SSE 진행 이벤트 | MVP |
| 검토 | POST | `/api/v1/reviews/{review_id}/retry` | 검토 재시도 | MVP |
| 결과 | GET | `/api/v1/reviews/{review_id}/result` | 결과·요약·필터 | MVP |
| 결과 | GET | `/api/v1/reviews/{review_id}/standard-clauses/{clause_id}` | 표준조항 원문 | MVP |
| 근거 | GET | `/api/v1/reviews/{review_id}/grounding` | 법령 근거 | MVP |
| 챗봇 | POST | `/api/v1/reviews/{review_id}/chat/messages` | 결과 기반 QA | MVP |
| 제안 | POST | `/api/v1/reviews/{review_id}/suggestions` | 기본 협의 문구 | MVP |
| 제안 | PATCH | `/api/v1/reviews/{review_id}/suggestions/{suggestion_id}` | 제안 편집 | 이후 |
| 재검토 | POST | `/api/v1/reviews/{review_id}/clause-reviews` | 단일 조항 재검토 | 이후 |
| 취소 | DELETE | `/api/v1/reviews/{review_id}` | 검토 취소 | 이후 |

## 4. 공통 계약

### 4.1 성공

```json
{
  "data": {},
  "meta": {
    "request_id": "req_01J...",
    "timestamp": "2026-07-23T05:30:00Z"
  }
}
```

### 4.2 오류

```json
{
  "error": {
    "code": "UNSUPPORTED_FILE_TYPE",
    "message": "지원하지 않는 파일 형식입니다.",
    "field": "file",
    "retryable": false,
    "next_actions": ["SELECT_ANOTHER_FILE"],
    "details": {}
  },
  "meta": {
    "request_id": "req_01J...",
    "timestamp": "2026-07-23T05:30:00Z"
  }
}
```

운영 응답에는 서버 경로, 내부 설정, API 키, 스택 트레이스, 계약·대화 본문을 포함하지 않는다.

### 4.3 주요 HTTP 상태

| HTTP | 의미 |
| --- | --- |
| `200` | 조회·수정 성공 |
| `201` | 세션 생성 |
| `202` | 비동기 작업 접수 |
| `400` | 현재 흐름에서 허용되지 않는 요청 |
| `404` | 없거나 접근할 수 없는 리소스 |
| `409` | 중복 실행·멱등성·상태 충돌 |
| `410` | 만료된 세션 또는 검토 |
| `413` | 파일 크기 초과 |
| `415` | 지원하지 않거나 실제 형식이 다른 파일 |
| `422` | 입력·근거·출력 검증 실패 |
| `429` | 요청 빈도·동시성 제한 초과 |
| `502` | MCP·LLM 응답 계약 오류 |
| `503` | MCP·코퍼스·모델·법령 서비스 사용 불가 |
| `504` | 외부 처리 시간 초과 |

### 4.4 멱등성

검토 시작·재시도·챗봇·협의 문구 생성은 `Idempotency-Key`를 요구한다.

- 동일 키·동일 요청: 기존 응답 반환
- 동일 키·다른 본문: `409 IDEMPOTENCY_KEY_REUSED`

관련 요구사항: `FR-2-11`

### 4.5 세션·수명

- 추측 불가능한 세션 토큰으로 사용자별 데이터를 격리한다.
- 권한 없는 리소스와 없는 리소스는 동일하게 `404`로 응답한다.
- 계약서와 대화 이력은 영구 저장하지 않는다.
- 완료·실패·취소 후 삭제를 시도한다.
- 미정 TTL 만료와 서버 재시작 후 잔존 파일을 정리한다.
- 임시 저장소는 백업 대상에서 제외한다.

관련 요구사항: `FR-5-8`, `FR-7-2`, `FR-7-8`, `FR-7-10`

## 5. 설정·메타데이터

### 5.1 `GET /api/v1/config`

```json
{
  "data": {
    "upload": {
      "max_file_size_bytes": null,
      "supported_extensions": ["hwp", "hwpx", "hwpml", "pdf", "xls", "xlsx", "docx"]
    },
    "limits": {
      "max_concurrent_reviews_per_session": null,
      "max_requests_per_hour": null
    },
    "session": {"ttl_seconds": null},
    "features": {
      "chat": true,
      "basic_suggestion": true,
      "confidence_score": false,
      "out_of_list_opinion": false,
      "suggestion_options": false,
      "suggestion_alternatives": false,
      "redline": false,
      "suggestion_edit": false,
      "single_clause_rereview": false,
      "server_side_cancel": false
    }
  }
}
```

`null`은 요구사항에서 값이 확정되지 않았음을 뜻한다.

### 5.2 목록 API

`GET /api/v1/contract-types`

- MCP `list_contract_types` 기반 동적 목록
- `code`, `label`, `description`, 캐시 상태 반환
- 프론트 enum 하드코딩 금지

`GET /api/v1/categories`

- MCP `list_categories` 기반 필터 카테고리

`GET /api/v1/toxic-patterns`

- MCP `list_toxic_pattern_details` 기반 코드·사람이 읽는 제목
- 제목 누락 시 중립적인 폴백 표시명

관련 요구사항: `FR-1-5`, `FR-1-9`, `FR-2-7`, `FR-3-2`

## 6. 업로드·유형 확인

### 6.1 `POST /api/v1/review-sessions`

Content-Type: `multipart/form-data`

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `file` | binary | Y | 계약서 |
| `external_llm_consent` | boolean | N | 외부 LLM 전송 동의 |

검증 순서:

1. 파일명·확장자
2. 지원 확장자·대소문자
3. 미정 최대 파일 크기
4. 확장자와 실제 형식
5. 암호화·손상 여부
6. 서버 생성 임시 경로
7. MCP transport별 XOR 입력
8. `assess_contract_scope` 유형 판별

성공 `201`:

```json
{
  "data": {
    "session_id": "ses_01J...",
    "upload": {
      "status": "COMPLETED",
      "file_name": "계약서.pdf",
      "size_bytes": 421398,
      "extension": "pdf"
    },
    "scope": {
      "status": "CONTRACT_TYPE_UNCERTAIN",
      "message": "계약 유형을 선택해 주세요.",
      "suggested_contract_type": "SOFTWARE_DEVELOPMENT",
      "selected_contract_type": null,
      "selection_source": null,
      "candidates": [
        {
          "contract_type": "SOFTWARE_DEVELOPMENT",
          "label": "소프트웨어 개발·구축",
          "score": 82
        }
      ]
    },
    "allowed_actions": ["SELECT_CONTRACT_TYPE"],
    "expires_at": null
  }
}
```

| `scope.status` | 의미 | 다음 행동 |
| --- | --- | --- |
| `READY` | 후보 판별 완료 | 유형 확정 |
| `CONTRACT_TYPE_UNCERTAIN` | 유형 근거 부족 | 직접 선택 |
| `OUT_OF_SCOPE` | 코퍼스 공통 근거 부족 | 선택·재확인 |
| `EMPTY_DOCUMENT` | 분석 본문 없음 | 재업로드 |

점수는 MCP가 반환한 경우에만 보존하며 MVP 화면에는 노출하지 않는다.

오류:

- `FILE_EXTENSION_MISSING`
- `UNSUPPORTED_FILE_TYPE`
- `FILE_SIGNATURE_MISMATCH`
- `FILE_TOO_LARGE`
- `EMPTY_DOCUMENT`
- `ENCRYPTED_DOCUMENT`
- `CORRUPTED_DOCUMENT`
- `UPLOAD_FAILED`

관련 요구사항: `FR-1-1~4`, `FR-1-8`, `FR-1-11`, `FR-7-4`, `FR-7-9~10`

### 6.2 `GET /api/v1/review-sessions/{session_id}`

새로고침, 화면 이동 또는 일시적인 연결 끊김 이후 업로드·계약 유형 확인 상태를 복구한다. 조회만으로 세션 TTL을 연장하지 않는다.

성공 `200`:

```json
{
  "data": {
    "session_id": "ses_01J...",
    "upload": {
      "status": "COMPLETED",
      "file_name": "계약서.pdf",
      "size_bytes": 421398,
      "extension": "pdf"
    },
    "scope": {
      "status": "CONTRACT_TYPE_UNCERTAIN",
      "message": "계약 유형을 선택해 주세요.",
      "suggested_contract_type": "SOFTWARE_DEVELOPMENT",
      "selected_contract_type": null,
      "selection_source": null,
      "out_of_scope_confirmed": false,
      "candidates": [
        {
          "contract_type": "SOFTWARE_DEVELOPMENT",
          "label": "소프트웨어 개발·구축",
          "score": 82
        }
      ]
    },
    "allowed_actions": ["SELECT_CONTRACT_TYPE"],
    "review_id": null,
    "expires_at": null
  },
  "meta": {
    "request_id": "req_01J...",
    "timestamp": "2026-07-24T01:00:00Z"
  }
}
```

규칙:

- 세션 생성 응답과 동일한 `upload`, `scope`, `allowed_actions` 구조를 사용한다.
- 검토가 생성된 경우 `review_id`를 반환하고, 생성 전에는 `null`이다.
- 추천 유형과 사용자 확정 유형을 분리한다.
- 점수는 MCP가 반환한 경우에만 보존하며 MVP 화면에는 노출하지 않는다.
- 세션 소유권이 없거나 존재하지 않으면 동일하게 `404`를 반환한다.
- TTL이 만료된 세션은 `410 SESSION_EXPIRED`를 반환한다.
- 서버 경로와 임시파일 위치는 응답에 포함하지 않는다.

오류:

- `SESSION_EXPIRED`

관련 요구사항: `FR-1-4~8`, `FR-5-8`, `FR-7-2`, `FR-7-8~10`

### 6.3 유형 확정

`PATCH /api/v1/review-sessions/{session_id}/contract-type`

```json
{
  "selected_contract_type": "SOFTWARE_DEVELOPMENT",
  "out_of_scope_confirmed": true
}
```

응답은 추천 유형, 사용자 확정 유형, 선택 주체를 분리한다.

오류:

- `UNSUPPORTED_CONTRACT_TYPE`
- `CONTRACT_TYPE_SELECTION_REQUIRED`
- `OUT_OF_SCOPE_CONFIRMATION_REQUIRED`
- `SESSION_EXPIRED`

관련 요구사항: `FR-1-4~7`, `FR-1-9~10`

## 7. 검토·진행

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
    "status": "QUEUED",
    "processing_status": "PENDING",
    "snapshot": {
      "contract_type": "SOFTWARE_DEVELOPMENT",
      "corpus_version": null,
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
      "result": "/api/v1/reviews/rev_01J.../result"
    }
  }
}
```

애플리케이션 `status`:

`QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `EXPIRED`

MVP 이후: `CANCEL_REQUESTED`, `CANCELLED`

MCP `processing_status`:

`PENDING`, `OK`, `CORPUS_UNAVAILABLE`, `INVALID_CONFIG`, `PIPELINE_ERROR`

관련 요구사항: `FR-1-6~8`, `FR-2-8~13`

### 7.2 SSE

`GET /api/v1/reviews/{review_id}/events`

이벤트: `progress`, `completed`, `failed`, `resync_required`

```text
id: 17
event: progress
data: {"review_id":"rev_01J...","sequence":17,"status":"RUNNING","stage":"CLAUSE_REVIEW","current":7,"total":17,"percent":61,"message":"제7조를 확인하고 있습니다."}
```

규칙:

- 실제 MCP progress를 사용한다.
- 모든 이벤트에 `review_id`를 연결한다.
- 이전 `sequence`는 지연·중복으로 폐기한다.
- `percent`는 서버에서 역행하지 않게 정규화한다.
- 재연결 시 `Last-Event-ID`를 사용할 수 있다.
- 복구 불가 시 상태 조회 API로 전환한다.
- 완료·실패 시 진행 표시를 종료한다.
- 오류 이벤트에 마지막 성공 단계와 `retryable`을 포함한다.

관련 요구사항: `FR-8-1~5`

### 7.3 상태·재시도

`GET /api/v1/reviews/{review_id}`

- SSE 연결 끊김·새로고침 복구용
- 현재 상태, 마지막 진행, 오류, 재시도 가능 여부 반환

`POST /api/v1/reviews/{review_id}/retry`

- `retryable=true`인 실패만 허용
- 세션 입력이 만료되지 않아야 함
- 새 `review_id`와 `retry_of` 반환
- 멱등성 키로 중복 차단

## 8. 검토 결과

### 8.1 `GET /api/v1/reviews/{review_id}/result`

Query: `deviation`, `category`, `keyword`, `cursor`, `limit`

```json
{
  "data": {
    "review": {
      "review_id": "rev_01J...",
      "status": "COMPLETED",
      "processing_status": "OK",
      "contract_type": "SOFTWARE_DEVELOPMENT",
      "corpus_version": null,
      "model_version": null,
      "started_at": "2026-07-23T05:30:00Z",
      "completed_at": "2026-07-23T05:32:00Z",
      "expires_at": null,
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
    "missing_standard_clauses": [],
    "page": {"next_cursor": null, "has_more": false}
  }
}
```

조항 결과:

```json
{
  "clause_id": "clause-7",
  "source": {
    "title": "제7조 손해배상",
    "text": "...",
    "location": {"page": 3, "anchor": "clause-7"}
  },
  "deviation": {
    "code": "EXTRA",
    "label": "표준조항 대비 추가 내용",
    "direction": "USER_TO_STANDARD"
  },
  "match": {
    "status": "CANDIDATE_SELECTED",
    "standard": {
      "standard_clause_id": "std-12",
      "title": "손해배상",
      "category": {"code": "LIABILITY", "label": "책임"}
    }
  },
  "comparison_reason": "...",
  "toxic_patterns": [
    {
      "code": "UNLIMITED_LIABILITY",
      "title": "책임 범위 확인 필요",
      "reason": "책임 한도가 명시되지 않은 표현과 유사합니다."
    }
  ]
}
```

규칙:

- `NONE`, `EXTRA`, `NO_MATCH`는 `clause_results`에 둔다.
- `MISSING`은 `missing_standard_clauses`에 별도로 둔다.
- `NO_MATCH`는 사용자 조항 → 표준조항 방향이다.
- `MISSING`은 표준조항 → 계약서 전체 방향이다.
- 주의 문구 후보는 deviation과 독립적으로 표시한다.
- 빈 패턴을 안전·적법으로 해석하지 않는다.
- 최상위 `processing_status`를 배열보다 먼저 확인한다.
- 빈 결과를 “문제 없음”으로 표시하지 않는다.
- 요약과 목록은 동일 스냅샷에서 계산한다.
- MVP에서는 점수·신뢰도를 노출하지 않는다.
- `related_risk_clauses`는 MVP UI·요약·챗봇에서 사용하지 않는다.

관련 요구사항: `FR-2-1~13`, `FR-3-1~6`, `FR-4-1~5`

### 8.2 표준조항 원문

`GET /api/v1/reviews/{review_id}/standard-clauses/{clause_id}`

응답: `standard_clause_id`, `title`, `text`, `category`, `version`

오류: `STANDARD_CLAUSE_NOT_FOUND`, `STANDARD_RESOURCE_UNAVAILABLE`

관련 요구사항: `FR-4-3`

## 9. 법령 근거

`GET /api/v1/reviews/{review_id}/grounding?category={code}`

```json
{
  "data": {
    "category": {"code": "LIABILITY", "label": "책임"},
    "items": [
      {
        "source_id": "law-1",
        "law_name": "민법",
        "article": "제390조",
        "text": "...",
        "source_url": "https://...",
        "retrieved_at": "2026-07-23T05:35:00Z"
      }
    ]
  }
}
```

- 법령명, 조번호, 본문, 출처를 분리한다.
- 법령 원문과 LLM 설명을 합치지 않는다.
- 정상 빈 결과와 외부 오류를 구분한다.
- 빈 결과를 법적 결론으로 해석하지 않는다.

오류: `GROUNDING_UNAVAILABLE`, `GROUNDING_TIMEOUT`, `GROUNDING_RESPONSE_INVALID`

관련 요구사항: `FR-5-1~4`

## 10. 챗봇

`POST /api/v1/reviews/{review_id}/chat/messages`

```json
{
  "message": "제7조에서 확인할 부분을 설명해 줘.",
  "context": {
    "clause_ids": ["clause-7"],
    "standard_clause_ids": ["std-12"],
    "law_source_ids": ["law-1"]
  }
}
```

응답은 `answer`, 검증된 `citations`, disclaimer를 포함한다.

안전 규칙:

- 현재 계약서와 검토의 근거만 사용한다.
- 실질 답변에는 출처가 필요하다.
- 출처 ID가 현재 세션에 존재하는지 검증한다.
- MCP 상태와 근거를 변경하지 않는다.
- 없는 조항과 출처를 생성하지 않는다.
- 문서 내 지시문을 시스템 명령으로 실행하지 않는다.
- 구조화 출력 검증을 통과한 답변만 표시한다.
- MCP 실패 시 추측 답변을 생성하지 않는다.
- 대화 이력을 영구 저장하지 않는다.

오류:

- `CHAT_CONTEXT_INVALID`
- `GROUNDING_REQUIRED`
- `MCP_UNAVAILABLE`
- `LLM_OUTPUT_INVALID`
- `LLM_CITATION_INVALID`
- `EXTERNAL_LLM_CONSENT_REQUIRED`

관련 요구사항: `FR-5-1~11`, `FR-7-4`

## 11. 협의 문구

`POST /api/v1/reviews/{review_id}/suggestions`

```json
{
  "clause_id": "clause-7",
  "purpose": "책임 범위를 명확히 하기 위한 협의 문구"
}
```

응답:

```json
{
  "data": {
    "suggestion_id": "sug_01J...",
    "clause_id": "clause-7",
    "text": "손해배상 책임의 범위와 한도는 [금액 확인 필요]로 협의한다.",
    "purpose": "책임 범위를 협의할 수 있도록 기준을 명확히 합니다.",
    "key_changes": ["책임 한도 확인 항목 추가"],
    "standard_clause_ids": ["std-12"],
    "required_confirmations": [
      {"field": "liability_limit", "placeholder": "[금액 확인 필요]"}
    ],
    "disclaimer": "계약서 수정본이 아닌 협의용 참고 초안입니다."
  }
}
```

안전 규칙:

- 선택 조항·표준조항·상태·카테고리·사용자 목적만 근거로 사용한다.
- 생성 목적, 차이, 근거 ID를 구조화한다.
- 단정적 법률 표현을 사용하지 않는다.
- 없는 금액, 기간, 비율, 사업 조건을 생성하지 않는다.
- 미정 값은 플레이스홀더로 제공한다.
- 근거 부족·검증 실패 시 임의 문구를 생성하지 않는다.
- 원본 계약서에 자동 반영하지 않는다.

관련 요구사항: `FR-6-1~8`

MVP 이후: 생성 방향, 복수 대안, 레드라인, 편집, 단일 조항 재검토(`FR-6-9~13`)

## 12. 프론트 상태 계약

| 화면 | 로딩 | 빈 상태 | 오류 | 다음 행동 |
| --- | --- | --- | --- | --- |
| 설정 | 스켈레톤 | 유형 없음 | 목록 실패 | 재조회 |
| 업로드 | 실제 전송률 | 해당 없음 | 원인별 | 파일 재선택 |
| 유형 | 문서 확인 중 | 후보 없음 | EMPTY·OUT_OF_SCOPE | 선택·재업로드 |
| 진행 | 실제 SSE | 해당 없음 | 마지막 단계 | 조건부 재시도 |
| 결과 | 스냅샷 로딩 | 중립적 빈 결과 | status별 | 조건부 재시도 |
| 표준·법령 | 영역 로딩 | 조회 결과 없음 | 외부 오류 | 재조회 |
| 챗봇·제안 | 생성 중 | 시작 안내 | 근거·출력 오류 | 입력 보완 |

금지 표현: 안전함, 적법함, 불법, 무효, 문제 없음, 유리·불리

권장 표현: 대응 표준조항 있음, 표준 대비 추가 내용, 대응 후보 없음, 누락 가능 표준조항 후보, 주의 문구 후보

## 13. 오류 코드

| 코드 | HTTP | 재시도 |
| --- | ---: | --- |
| `FILE_EXTENSION_MISSING` | 422 | N |
| `UNSUPPORTED_FILE_TYPE` | 415 | N |
| `FILE_SIGNATURE_MISMATCH` | 415 | N |
| `FILE_TOO_LARGE` | 413 | N |
| `EMPTY_DOCUMENT` | 422 | N |
| `ENCRYPTED_DOCUMENT` | 422 | N |
| `CORRUPTED_DOCUMENT` | 422 | N |
| `SESSION_EXPIRED` | 410 | N |
| `CONTRACT_TYPE_SELECTION_REQUIRED` | 400 | N |
| `OUT_OF_SCOPE_CONFIRMATION_REQUIRED` | 400 | N |
| `REVIEW_ALREADY_RUNNING` | 409 | N |
| `REVIEW_NOT_COMPLETED` | 409 | Y |
| `IDEMPOTENCY_KEY_REUSED` | 409 | N |
| `RATE_LIMIT_EXCEEDED` | 429 | Y |
| `CORPUS_UNAVAILABLE` | 503 | 조건부 |
| `INVALID_CONFIG` | 500 | N |
| `PIPELINE_ERROR` | 500 | 조건부 |
| `MCP_RESPONSE_INVALID` | 502 | 조건부 |
| `GROUNDING_UNAVAILABLE` | 503 | Y |
| `GROUNDING_TIMEOUT` | 504 | Y |
| `LLM_OUTPUT_INVALID` | 502 | 조건부 |
| `LLM_CITATION_INVALID` | 502 | 조건부 |
| `INSUFFICIENT_GROUNDING` | 422 | N |
| `REQUIRED_VALUE_MISSING` | 422 | N |
| `GENERATED_FACT_NOT_GROUNDED` | 502 | 조건부 |
| `EXTERNAL_LLM_CONSENT_REQUIRED` | 409 | N |

## 14. MCP 응답 정규화

| 원본 | API 처리 | 화면 |
| --- | --- | --- |
| 선택 필드 `null` | `null` 유지 | 사용자 선택 |
| 목록 `[]` | 빈 배열 유지 | 중립적 빈 상태 |
| 필수 필드 누락 | `502 MCP_RESPONSE_INVALID` | 결과 미표시 |
| 알 수 없는 enum | `502 MCP_RESPONSE_INVALID` | 버전 오류 |
| 최상위 오류 | `processing_status` 보존 | 상태별 오류 |
| `related_risk_clauses` | MVP DTO에서 제거 | 표시·판단 제외 |

`clause_results`와 `missing_standard_clauses`는 합치지 않는다.

관련 요구사항: `FR-1-11`, `FR-2-1~2`, `FR-2-8~10`

## 15. 보안·운영

- 민감정보 전송 구간에 TLS를 적용한다.
- 키와 접속정보를 클라이언트·저장소·이미지·로그에 포함하지 않는다.
- 운영 로그에는 비식별 기술 메타데이터만 기록한다.
- 사용자 입력을 서버 경로나 명령에 직접 사용하지 않는다.
- 사용자·세션별 데이터와 요청을 격리한다.
- 파일 크기, 동시 검토, 시간당 요청을 제한한다.
- 자체 호스팅 LLM을 기본으로 사용한다.
- 외부 LLM은 사전 동의 없이 자동 폴백하지 않는다.

관련 요구사항: `FR-7-1~10`

## 16. 배포 전 필수 계약 테스트

1. 지원 형식·대소문자·손상·암호화
2. MCP XOR·형식 불일치·빈 문서·크기 초과
3. 유형 후보 정렬·빈 배열·동점·선택 전달
4. 유형 선택 전 검토 차단
5. OUT_OF_SCOPE 재확인 전후
6. MVP 점수·신뢰도 비노출
7. 최상위 오류 상태별 정책
8. 상태별 빈 결과 화면
9. 패턴 제목 누락 폴백
10. MISSING 기준과 건수
11. 표준조항 원문·오류
12. 법령 출처·빈 결과·외부 오류
13. 완료·실패·취소·TTL·재시작 후 삭제
14. 앱·디버그·APM 본문 비수집
15. progress 순서·완료·오류·연결 끊김
16. 선택 필드 누락·null·빈 배열

## 17. 미확정 사항

1. 최대 파일 크기
2. 세션·임시파일 TTL
3. 사용자·IP별 요청 빈도
4. 세션별 동시 검토 수
5. 지원 브라우저와 인증 범위
6. 원문 위치 좌표 방식
7. 결과 페이지네이션
8. 계약 유형 캐시 TTL
9. SSE 이벤트 보존·재연결 범위
10. 코퍼스·모델 버전 출처
11. 외부 LLM 동의 범위·기간
12. 협의 문구 목적 선택지

화면설계·배포설계·성능시험 후 확정하고 API 버전을 갱신한다.
