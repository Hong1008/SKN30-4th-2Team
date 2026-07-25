# 7. 검토 시작·상태 조회

## 7.1 `POST /api/v1/reviews`

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

## 7.2 상태 코드

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

## 7.3 `GET /api/v1/reviews/{review_id}`

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

## 8.1 `GET /api/v1/reviews/{review_id}/events`

이벤트:

```text
progress
completed
failed
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

## 9.1 `POST /api/v1/reviews/{review_id}/retry`

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

## 10.1 `GET /api/v1/reviews/{review_id}/results`

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

## 10.2 사용자 조항 결과

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

## 10.3 MISSING 체크리스트

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

## 10.4 결과 규칙

- 최상위 `mcp_review_status`를 배열보다 먼저 확인한다.
- `mcp_review_status != OK`이면 결과 배열을 표시하지 않는다.
- `toxic_patterns=[]`는 안전함을 뜻하지 않는다.
- 요약 수치와 결과 배열은 동일한 스냅샷에서 계산한다.
- 알 수 없는 MCP enum은 임의 라벨로 정상 처리하지 않고 `502 MCP_RESPONSE_INVALID`로 처리한다.

---

