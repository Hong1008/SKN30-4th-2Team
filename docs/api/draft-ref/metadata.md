# 4. 메타데이터

## 4.1 `GET /api/v1/metadata`

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
    "result_codes": ["NONE", "EXTRA", "NO_MATCH", "MISSING"],
    "result_code_details": [
      {"code": "NONE", "label": "표준 대응 후보 있음"},
      {"code": "EXTRA", "label": "별도 확인 필요"},
      {"code": "NO_MATCH", "label": "표준조항 검색 후보 없음"},
      {"code": "MISSING", "label": "표준조항 누락 가능성"}
    ],
    "progress_stages": [],
    "grounding_statuses": [],
    "chat_outcomes": [],
    "draft_outcomes": [],
    "error_codes": [],
    "selection_sources": [],
    "next_actions": [],
    "file_policy": {
      "extensions": ["hwp", "hwpx", "pdf", "docx"],
      "max_size_bytes": 10485760,
      "single_file_only": true,
      "encrypted_file_allowed": false
    },
    "features": {
      "chat": true,
      "basic_suggestion": true,
      "confidence_score": false,
      "suggestion_edit": false,
      "single_clause_rereview": false,
      "server_side_cancel": true
    }
  }
}
```

계약 유형 원본 목록은 MCP `list_contract_types`를 기준으로 검증한다. 제품 MVP에서는 `enabled_for_mvp=true`인 세 유형만 선택할 수 있다.

## 4.2 캐시

백엔드는 MCP의 계약 유형·카테고리·주의 문구 메타데이터를 5~10분 캐시한다.

권장 헤더:

```http
Cache-Control: public, max-age=300, stale-while-revalidate=600
ETag: "metadata-1.1-20260724"
```

프론트는 요청 라이브러리의 메모리 캐시를 사용한다. MVP에서는 `localStorage` 영속 캐시를 사용하지 않는다.

## 4.3 메타데이터 코드

## 범위 판별 상태

```text
IN_SCOPE
CONTRACT_TYPE_UNCERTAIN
OUT_OF_SCOPE
EMPTY_DOCUMENT
```

## 검토 세션 상태

```text
ANALYZING_CONTRACT_TYPE
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

## 결과 코드

```text
NONE
EXTRA
NO_MATCH
MISSING
```

`MISSING`의 `group`은 `STANDARD_CHECKLIST`, 나머지는 `CLAUSE_RESULT`이다.

## 진행 단계

```text
PREPARE
BATCH_SEARCH
RERANK
CLAUSE_REVIEW
MISSING_DETECTION
RESULT_ASSEMBLY
```

## 법령 조회 상태

```text
OK
NO_RESULT
UNMAPPED_CATEGORY
UPSTREAM_ERROR
TIMEOUT
```

## 선택 경로

```text
SUGGESTED
CANDIDATE
MANUAL
```

## 다음 행동

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

