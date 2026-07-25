# 0724 WorkShield MVP API 완성

- 상태: 승인됨
- 구현 상태: `feat/mvp-api` 로컬 검증 완료, main 반영 대기
- 결정일: 2026-07-24
- 대상 브랜치: `feat/mvp-api`
- 기준 커밋: `e658b0d feat(api): 세션 및 리뷰 API 기본 흐름 구현`
- 관련 ADR:
  - `0723-api-setting.md`
  - `0724-anonymous-session-file-storage.md`
  - `0724-llm-risk.md`
  - `0724-minimal-operations.md`
  - `0724-sqlite-persistence.md`

## 맥락

기준 커밋에는 익명 세션 생성, HttpOnly Cookie 소유권 검증, 임시 파일
저장소, 계약 유형 선택, 검토 접수·상태·결과·재시도와 기본 SSE 흐름이
구현되어 있었다. 그러나 프론트엔드가 MVP 전체 사용자 흐름을 연결하려면
다음 기능이 추가로 필요했다.

- API 성공·오류 응답과 HTTP 상태 매핑 통일
- 요청 본문까지 구분하는 범용 멱등 처리
- 계약 유형·카테고리·상태·오류 코드를 제공하는 metadata
- 실제 MCP 진행 이벤트와 검토 상태 연결
- 검토 결과 카테고리별 법령 근거 조회
- 현재 검토 근거 안에서만 동작하는 Chat
- 사용자 조항과 대응 표준조항 기반 Suggestions
- 사용자 활동 기준 sliding TTL, 결과 폐기형 취소와 반복 가능한 정리
- 전체 흐름, 브라우저 세션 격리와 장애 복구를 검증하는 통합 테스트

WorkShield API는 MCP가 생성한 결정론적 검토 결과를 사실의 기준으로
사용한다. LLM은 해당 결과를 변경하지 않고 설명과 협의 문구를 만드는
제한된 역할만 수행해야 한다.

## 결정

### 1. 공통 API 응답과 오류 계약

- JSON 성공 응답은 `ApiResponse[T]`, 오류 응답은 `ApiErrorResponse`를
  사용한다.
- v1 Router의 OpenAPI 응답에 공통 `404`, `409`, `410`, `422`, `503`,
  `504` 오류 모델을 선언한다.
- 리소스가 없거나 현재 Cookie가 소유하지 않은 리소스는 모두
  `404 RESOURCE_NOT_FOUND`로 응답한다.
- 소유한 세션이 만료된 경우에만 `410 SESSION_EXPIRED`를 반환한다.
- `ExternalServiceTimeoutError`를 일반 외부 서비스 오류보다 먼저
  매핑하여 `504`가 `503`으로 변환되지 않도록 한다.
- 보호 API는 `OwnedReviewSessionDep` 또는 `OwnedReviewDep`를 사용하고,
  body에 `session_id`가 있는 검토 생성 API는 같은 소유권 resolver를
  재사용한다.
- APIKey Cookie security scheme을 OpenAPI에 노출한다.

### 2. 범용 멱등 처리

`idempotency_records` 테이블을 추가한다.

| 필드 | 용도 |
|---|---|
| `scope` | API 동작 구분 |
| `session_id` | 익명 세션 범위 |
| `idempotency_key` | 클라이언트가 보낸 키 |
| `request_fingerprint` | 정규화된 요청 JSON의 SHA-256 |
| `response_snapshot` | 같은 요청에 반환할 응답 데이터 |
| `created_at` | 최초 성공 시각 |
| `expires_at` | 제한된 보존 만료 시각 |

`scope + session_id + idempotency_key`를 unique key로 사용한다.

- 동일 키·동일 fingerprint: 저장된 응답을 반환한다.
- 동일 키·다른 fingerprint: `409 IDEMPOTENCY_KEY_REUSED`를 반환한다.
- Chat과 Suggestions의 fingerprint에는 `review_id`를 포함하여 같은
  세션의 다른 review에서 키를 재사용하지 못하게 한다.
- 단일 프로세스에서는 동일한 외부 호출을 async lock으로 직렬화하고,
  다중 프로세스 경쟁은 DB unique 제약과 승자 응답 재조회로 수렴시킨다.
- 검토 접수와 멱등 응답 스냅샷은 같은 DB commit으로 저장한다.
- 기존 `reviews.idempotency_key`에는 scope를 반영한 내부 해시 키를
  저장하여 legacy unique 제약과 API scope가 충돌하지 않게 한다.
- 멱등 레코드는 세션 TTL 안에서만 보존하며 정리 주기에 삭제한다.
- 적용 API:
  - `POST /api/v1/reviews`
  - `POST /api/v1/reviews/{review_id}/retry`
  - `POST /api/v1/reviews/{review_id}/chat/messages`
  - `POST /api/v1/reviews/{review_id}/suggestions`

### 3. Metadata API

`GET /api/v1/metadata`를 추가한다.

다음 MCP 도구의 응답을 정규화한다.

- `list_contract_types`
- `list_categories`
- `list_toxic_pattern_details`

결정 사항:

- 메모리 캐시 TTL은 기본 5분이다.
- MCP 장애 시 프로세스에 마지막 정상 캐시가 있으면 stale 응답을
  제공하고 `Warning: 110`을 설정한다.
- 마지막 정상 캐시도 없으면 `503 MCP_METADATA_UNAVAILABLE`을 반환한다.
- `Cache-Control`, `ETag`, `If-None-Match`와 `304`를 지원한다.
- null, 누락 필드, 빈 배열과 알 수 없는 항목을 안전하게 정규화한다.
- 제품 MVP에서 활성화하는 계약 유형은 다음 세 가지로 제한한다.
  - `SW_FREELANCE`
  - `SI_SUBCONTRACT`
  - `SM_SUBCONTRACT`
- 프론트가 계약 유형, 카테고리, 상태, 오류 코드, 다음 행동과 기능
  플래그를 하드코딩하지 않도록 한 응답에 포함한다.

### 4. Review 실행과 진행 이벤트

전체 검토에는 WorkShield MCP의 권장 도구
`review_contract_candidates`를 사용한다.

- MCP `ClientSession.call_tool()`의 `progress_callback`을 직접 연결한다.
- progress를 `review_id`별 DB 상태에 기록한다.
- `sequence`는 review 내부에서만 증가한다.
- `current / total`로 계산한 percent가 이전 값보다 작아지면 이전 값을
  유지한다.
- 진행 단계는 `PREPARE`, `BATCH_SEARCH`, `RERANK`, `CLAUSE_REVIEW`,
  `MISSING_DETECTION`, `RESULT_ASSEMBLY`로 정규화한다.
- MCP 결과는 다음 배열을 항상 분리해서 보존한다.
  - `clause_results`
  - `missing_standard_clauses`
  - 각 `clause_results[].toxic_patterns`
- 실제 MCP 공개 DTO를 `extra=forbid`로 검증하고 필수 필드·enum·유니온
  위반은 `MCP_RESPONSE_INVALID` 실패로 처리한다.
- 결과 순서로 `uc_{review_id}_{1부터 시작하는 순번}` ID를 생성한다.
- 두 최상위 결과 배열의 누락 또는 null은 빈 배열로 정규화한다.
- `GET /results`는 저장 dict를 그대로 노출하지 않고
  `review`, `summary`, `clause_results`, `missing_standard_clauses` DTO로
  변환하며 내부 후보 점수는 노출하지 않는다.
- 상태 전이는 `QUEUED → REVIEWING → COMPLETED | FAILED`로 제한한다.
- SSE는 저장된 sequence를 사용하고 완료·실패·만료·취소 후 종료한다.
- `Last-Event-ID` 이하의 진행 이벤트는 다시 전송하지 않는다.
- SSE data는 `stage`, `current`, `total`, `percent`, `message`를 최상위에
  제공하고 terminal event에 `mcp_review_status`, `error`를 추가한다.
- SSE가 끊기면 프론트는 상태 조회 API로 동기화한 뒤 재연결한다.

MCP 상태와 실패 정책:

| 상태 또는 오류 | 최종 상태 | 재시도 |
|---|---|---|
| `OK` | `COMPLETED` | 해당 없음 |
| `CORPUS_UNAVAILABLE` | `FAILED` | 가능 |
| `PIPELINE_ERROR` | `FAILED` | 가능 |
| MCP timeout | `FAILED / MCP_TIMEOUT` | 가능 |
| `INVALID_CONFIG` | `FAILED` | 불가 |
| `EMPTY_DOCUMENT` | `FAILED` | 불가 |
| 공개 DTO 위반 | `FAILED / MCP_RESPONSE_INVALID` | 불가 |

서버가 재시작되면 남아 있던 `QUEUED`, `REVIEWING` 검토를
`FAILED / REVIEW_INTERRUPTED`로 복구한다. 이 오류는 재시도 가능하며,
복구 시점부터 세션 TTL을 다시 시작하여 원본 파일이 즉시 삭제되지 않게
한다.

### 5. Grounding API

`GET /api/v1/reviews/{review_id}/grounding?category=...`를 추가한다.

- `OwnedReviewDep`로 현재 브라우저의 review 소유권을 먼저 확인한다.
- `COMPLETED` review에서만 호출할 수 있다.
- 현재 review 결과에 카테고리 목록이 있으면 그 목록 밖의 category를
  거부한다.
- review에 저장된 `contract_type`과 검증된 category만 조합하여
  `get_category_grounding`을 호출한다.
- 응답은 `OK`, `NO_RESULT`, `UNMAPPED_CATEGORY`, `UPSTREAM_ERROR`,
  `TIMEOUT`으로 정규화한다.
- `NO_RESULT`, `UNMAPPED_CATEGORY`는 정상 구조 응답이다.
- URL은 `http` 또는 `https`로 검증된 경우에만 `source_url`로 제공한다.
- grounding 실패는 전체 review 상태를 `FAILED`로 변경하지 않는다.
- MCP의 원문 오류를 그대로 사용자에게 노출하거나 법령 본문을 로그에
  남기지 않는다.

### 6. Chat API

`POST /api/v1/reviews/{review_id}/chat/messages`를 추가한다.

- 완료된 현재 review의 결과와 필요한 category grounding만 LLM
  컨텍스트로 사용한다.
- `focus_clause_id`가 현재 review 결과에 있는지 확인한다.
- 계약서와 MCP 응답에 포함된 명령문은 실행 지시가 아닌 데이터로
  처리하도록 system prompt 경계를 둔다.
- LLM은 Pydantic 구조화 출력으로 `ANSWERED`, `REFUSED`,
  `INSUFFICIENT_GROUNDING`만 생성한다.
- 백엔드는 `USER_CLAUSE`, `STANDARD_CLAUSE`, `LAW` citation ID를 현재
  review와 grounding의 allowlist로 검증한다.
- `ANSWERED`인데 답변 또는 출처가 없거나, 존재하지 않는 citation을
  반환하면 `LLM_OUTPUT_INVALID`로 바꾼다.
- LLM timeout은 `504 LLM_TIMEOUT`으로 변환한다.
- 대화 이력을 별도 영구 테이블에 저장하지 않는다. 멱등 재사용을 위한
  응답 스냅샷만 세션 TTL 동안 제한적으로 보존한다.

### 7. Suggestions API

`POST /api/v1/reviews/{review_id}/suggestions`를 추가한다.

생성 전 다음 조건을 확인한다.

- 현재 review 소유권
- 완료된 review
- 요청한 사용자 조항 존재
- `match.status == CANDIDATE_SELECTED`
- 대응 표준조항과 표준조항 ID 존재
- category grounding 상태 `OK`
- 조항이 선언한 필수 입력값 존재

생성 후 다음 항목을 검증한다.

- 구조화 출력 DTO
- 반환된 표준조항 ID가 선택된 표준조항과 일치
- grounding source ID가 조회 결과 allowlist에 포함
- 생성 문구의 금액·기간·비율 등 숫자가 입력 컨텍스트에 존재

검증되지 않은 숫자를 만들면 `GENERATED_FACT_NOT_GROUNDED`, 출력이나
출처가 잘못되면 `LLM_OUTPUT_INVALID`를 반환한다. 원본 계약서는 자동으로
수정하지 않으며, 제안 본문은 별도 영구 리소스로 저장하지 않는다.

### 8. TTL, 취소와 정리

- 세션·review·grounding·chat·suggestions의 소유권 검증 성공 시 부모
  세션과 review의 `expires_at`을 기본 30분 뒤로 이동한다.
- 실행 중인 `QUEUED`, `REVIEWING` review는 만료로 차단하거나 정리하지
  않는다.
- 완료·실패·재시작 복구 후 TTL을 다시 시작한다.
- 새 검토를 같은 세션에서 시작하면 이전 검토의 민감 결과와 진행
  스냅샷을 제거하고 이전 검토를 만료 상태로 바꾼다.
- 재시도 가능한 실패는 원본 파일을 유지한다.
- 재시도 불가능한 실패는 원본 파일을 즉시 삭제한다.
- `DELETE /api/v1/reviews/{review_id}`는 강제 MCP 중단 보장 대신 현재
  작업을 취소 표시하고 결과·진행 정보와 원본 파일을 폐기한다.
- 삭제를 반복 호출해도 오류가 나지 않는다.
- 만료 시 파일, 범위 판별 원문, 검토 결과와 오류를 제거하고
  `EXPIRED` tombstone을 남긴다.
- tombstone은 기본 24시간 후 삭제한다.
- 파일·레코드 정리 실패는 다음 주기에서 다시 시도한다.

## 작업 과정

### 1. 기존 구현 경계 확인

`api/`, `docs/api/`, `docs/requirements/`와 다음 구현을 대조했다.

- DB row, domain, mapper와 repository
- 세션·review Router와 서비스
- MCP runtime과 tool loading 방식
- LLM provider 의존성
- FileStorage와 주기적 cleanup
- 기존 OpenAPI 및 프론트 전달 문서

기존 공통 응답과 소유권 dependency는 재사용하고, 기능별 패키지를
`metadata`, `grounding`, `chat`, `suggestions`, `idempotency`로 분리했다.

### 2. WorkShield MCP 계약 확인

프로젝트의 `workshield-mcp` 지침과 도구·응답 안전 규칙을 확인했다.

- 전체 검토는 `review_contract_candidates`를 우선 사용한다.
- 법령 근거는 결과에 내장된 값으로 가정하지 않고
  `get_category_grounding`을 별도 호출한다.
- metadata는 `list_contract_types`, `list_categories`,
  `list_toxic_pattern_details`를 사용한다.
- `clause_results`와 `missing_standard_clauses`를 합치지 않는다.
- 빈 배열을 성공으로 간주하기 전에 최상위 MCP `status`를 확인한다.
- MCP 결과는 법률 판단이 아닌 표준 대비 검토 후보로 취급한다.

설치된 MCP SDK의 `ClientSession.call_tool` 시그니처를 확인하여
`progress_callback(progress, total, message)`를 실제 실행에 연결했다.

### 3. TDD와 통합 검증

공통 기반과 각 API를 구현한 뒤 기존 테스트를 반복 실행했다. 변경 과정에서
다음 회귀를 발견하고 수정했다.

- active review가 있는 만료 세션의 기존 테스트 기대값과 새 TTL 정책 차이
- 새 `idempotency_records` 테이블로 인한 DB 스키마 테스트 변경
- 테스트용 Settings fixture에 새 tombstone TTL 설정이 없을 때의 호환성
- OpenAPI 문서 불일치
- Windows CP949 콘솔에서 OpenAPI 생성 스크립트의 체크 표시 출력 실패
- timeout 예외가 상위 외부 서비스 오류에 먼저 매핑되는 순서 문제

OpenAPI 생성 스크립트의 출력은 ASCII로 변경하고, 최종 스키마를
`docs/api/openapi.json`에 다시 생성했다.

## 결과

구현된 MVP API:

| Method | Path | 소유권 |
|---|---|---|
| `GET` | `/api/v1/metadata` | 공개 |
| `POST` | `/api/v1/review-sessions` | Cookie 발급 |
| `GET` | `/api/v1/review-sessions/{session_id}` | 세션 소유권 |
| `PATCH` | `/api/v1/review-sessions/{session_id}/contract-type` | 세션 소유권 |
| `POST` | `/api/v1/review-sessions/{session_id}/out-of-scope-confirmation` | 세션 소유권 |
| `POST` | `/api/v1/reviews` | body 세션 소유권 |
| `GET` | `/api/v1/reviews/{review_id}` | review 소유권 |
| `GET` | `/api/v1/reviews/{review_id}/results` | review 소유권 |
| `GET` | `/api/v1/reviews/{review_id}/events` | review 소유권 |
| `POST` | `/api/v1/reviews/{review_id}/retry` | review 소유권 |
| `GET` | `/api/v1/reviews/{review_id}/grounding` | review 소유권 |
| `POST` | `/api/v1/reviews/{review_id}/chat/messages` | review 소유권 |
| `POST` | `/api/v1/reviews/{review_id}/suggestions` | review 소유권 |
| `DELETE` | `/api/v1/reviews/{review_id}` | review 소유권 |

프론트엔드는 metadata 한 번으로 선택 목록과 상태·오류 코드를 구성할 수
있으며, `session_id`와 `review_id`만 복구 정보로 사용한다. 세션 접근
토큰은 계속 HttpOnly Cookie로만 전달한다.

## 검증

최종 검증 명령:

```text
cd api
uv run ruff check app main.py tests scripts
uv run pytest -q --basetemp=.codex-final-mvp-tests-2
git diff --check
```

최종 결과:

```text
Ruff: All checks passed
Pytest: 166 passed, 4 skipped
git diff --check: 통과
```

추가된 주요 검증:

- 세션 생성 → Cookie 발급 → 계약 유형 선택 → review 접수 → 완료
- 브라우저 A/B 세션 및 review 접근 격리
- 같은 멱등 키·같은 요청 replay
- 같은 멱등 키·다른 요청 `409 IDEMPOTENCY_KEY_REUSED`
- metadata 메모리 캐시와 ETag `304`
- MCP 결과의 null 배열 정규화
- 실제 MCP 공개 DTO 위반 거부와 canonical 사용자 조항 ID
- 결과 조회의 표시용 DTO·요약·MISSING 분리
- grounding category와 출처 정규화
- Chat focus clause와 citation allowlist
- Suggestions 표준조항·grounding citation·생성 숫자 검증
- MCP progress percent 역행 방지와 sequence 증가
- SSE 완료 이벤트 및 종료
- 서버 재시작 시 active review의 retryable 실패 복구
- 만료 세션 파일·민감 결과 삭제
- active review 만료 유예
- 반복 가능한 orphan 파일 정리와 취소
- OpenAPI 파일과 FastAPI runtime schema 일치

기본 회귀 테스트는 실제 외부 MCP·LLM을 호출하지 않고 동일한 runtime,
tool, structured-output 인터페이스를 제공하는 fake로 전체 API 흐름을
검증한다. 외부 의존성이 필요한 검증은 opt-in 통합 테스트로 분리했다.

2026-07-25 opt-in 사전 검증 결과:

- 실제 WorkShield MCP stdio BE-A 세션 흐름: 통과
- 실제 WorkShield MCP stdio BE-B Review/SSE 흐름: 통과
- Ollama Qwen3.5 4B Chat 구조·출처: 통과, 표현 품질 후속 필요
- Ollama Qwen3.5 4B Suggestions: 출처 누락으로 모델 품질 gate 실패,
  서버의 `LLM_OUTPUT_INVALID` 안전 차단 통과
- Gemini Gemma 4 31B 합성 fixture: Chat·Suggestions 각 3/3 통과,
  외부 전송 정책으로 운영 사용 금지

## 확인된 제한과 후속 검증

다음 항목은 코드와 자동화 테스트만으로 완료되었다고 판단하지 않는다.

- 운영 환경 streamable HTTP WorkShield MCP와 실제 서비스 주소·파일
  transport 연결
- 실제 MCP progress의 happy path는 stdio에서 확인했으나 운영 환경의
  단계 문자열, 발생 빈도와 오류 이벤트
- 운영 corpus를 사용한 `review_contract_candidates` 결과 품질
- 실제 `get_category_grounding` 원문·출처 필드 호환성
- Qwen3.5 4B는 Suggestions 품질 gate를 통과하지 못했으며 운영 Ollama
  모델은 아직 미선정
- 긴 계약서에서 Chat/Suggestions 컨텍스트 크기와 응답 시간
- 다중 프로세스 또는 다중 인스턴스 환경의 메모리 metadata 캐시
- 다중 인스턴스에서 Chat/Suggestions 외부 호출 자체의 분산 잠금
- 운영 로그·APM·reverse proxy에서 계약서, 토큰, 대화 본문 미수집 확인

따라서 배포 전 실제 운영 주소의 MCP E2E와 장애 주입 테스트를 별도로
수행해야 한다. LLM 기능을 활성화할 경우에는 승인된 정확한 Ollama 모델로
기능별 품질 gate도 다시 통과해야 한다. 해당 검증 전에는 자동화 테스트의
통과를 운영 품질 검증 완료로 해석하지 않는다.

## 고려한 대안

### API별 개별 멱등 처리

review row만 조회하는 방식은 Chat과 Suggestions에 재사용하기 어렵고,
동일 키의 다른 요청을 구분할 fingerprint가 없으므로 채택하지 않았다.

### 프론트 하드코딩 metadata

MCP와 API 상태가 변경될 때 프론트 배포가 함께 필요하고 표시 목록이
엇갈릴 수 있으므로 채택하지 않았다.

### 프론트 타이머 기반 진행률

실제 서버 상태와 무관하고 진행률이 완료 전에 100%가 되거나 역행할 수
있으므로 채택하지 않았다.

### grounding을 전체 검토 결과에 미리 포함

모든 카테고리의 법령 원문을 불필요하게 조회·저장하고, WorkShield MCP의
권장 도구 경계를 위반하므로 category 요청 시 별도 조회한다.

### LLM이 MCP 도구와 citation을 자율 선택

세션 범위 밖 정보 조회, 존재하지 않는 출처 생성과 prompt injection
위험이 커지므로 채택하지 않았다. API가 도구를 선택하고 LLM 출력은
allowlist로 검증한다.

### Chat과 Suggestions 영구 저장

MVP 복구에 필수적이지 않고 계약 내용과 대화가 장기 보존되는 위험이
있으므로 별도 영구 리소스로 저장하지 않는다.

## 재검토 조건

다음 중 하나가 발생하면 이 결정을 재검토한다.

- SQLite에서 PostgreSQL 또는 분산 DB로 전환한다.
- API 인스턴스를 여러 개 운영하여 메모리 캐시와 작업 상태를 공유해야 한다.
- 작업 queue 또는 별도 worker를 도입한다.
- MCP가 progress event replay 또는 작업 취소 API를 제공한다.
- Chat 대화 복구나 Suggestions 편집·임시 저장이 제품 요구사항에 포함된다.
- 세션 TTL 또는 tombstone 보존 기간이 개인정보 정책에 따라 변경된다.
- 실제 MCP·LLM E2E에서 DTO, 상태 코드 또는 timeout 정책 불일치가 확인된다.
- 운영 로그·APM에서 민감 본문이 수집되는 것으로 확인된다.
