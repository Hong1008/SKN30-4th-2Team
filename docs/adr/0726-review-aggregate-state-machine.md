# 0726 Review Aggregate 상태 머신과 진행률 일관성

- 상태: 승인됨
- 결정일: 2026-07-26
- 대상: WorkShield API Review 실행·복구·취소·만료 흐름
- 구현 커밋:
  - `50866eb feat(mcp): structure review progress events`
  - `a6c9cb7 feat(api): enforce review aggregate transitions`
  - `ea74ac1 test(api): fix core llm monkeypatch paths`
- 관련 ADR:
  - `0724-mvp-api-completion.md`
  - `0724-anonymous-session-file-storage.md`
  - `0724-sqlite-persistence.md`

## 맥락

기존 `Review`는 상태를 Enum으로 표현했지만 runner, API, lifespan, cleanup이
`state`, `progress`, `result`, `error`를 각각 직접 변경했다. 이 구조에서는
허용되지 않은 상태 전이와 서로 모순되는 스냅샷을 만들 수 있었다.

또한 MCP progress와 API 상태 저장이 별도 DB session에서 실행되므로 다음
경쟁을 고려해야 했다.

- 취소된 Review를 늦은 MCP 완료가 다시 `COMPLETED`로 덮어쓰기
- terminal Review를 늦은 progress가 `REVIEWING` 스냅샷으로 덮어쓰기
- 상태 조회의 sliding TTL 갱신과 progress 저장 사이의 version 충돌
- 서로 다른 멱등 키로 같은 세션에 여러 active Review 생성
- 같은 멱등 키의 동시 요청이 기존 응답 replay 대신 중복 실행되거나
  충돌 응답으로 끝나는 문제

MCP는 progress callback의 `message`에 한글 표시 문구만 전달했다. API는
영문 stage 또는 JSON stage를 기대했으므로 실제 연동에서 단계가
`PREPARE`에 머물 가능성도 있었다.

서버 종료 시에는 review task를 취소만 하고 회수하지 않았으며, MCP runtime이
task보다 먼저 닫힐 수 있었다. 취소·만료·재시도 불가능 실패에서 파일을 DB
상태 확정보다 먼저 삭제하면 DB rollback 이후 존재하지 않는 파일을 계속
참조할 위험도 있었다.

## 결정

### 1. Review를 상태 전이를 소유하는 Aggregate Root로 관리한다

`Review`의 상태와 progress는 외부에서 직접 대입할 수 없게 하고 다음
factory를 사용한다.

- `Review.queued()`: 새 `QUEUED` Review 생성
- `Review.restore()`: Mapper가 영속 스냅샷 복원

상태 변경은 다음 도메인 메서드로만 수행한다.

| 메서드 | 허용 전이 |
|---|---|
| `start()` | `QUEUED → REVIEWING` |
| `complete(mcp_status, result)` | `REVIEWING → COMPLETED` |
| `fail(error, mcp_status=None)` | `QUEUED/REVIEWING → FAILED` |
| `mark_interrupted()` | `QUEUED/REVIEWING → FAILED` |
| `cancel()` | `QUEUED/REVIEWING/COMPLETED/FAILED → CANCELLED` |
| `expire()` | `COMPLETED/FAILED/CANCELLED → EXPIRED` |

추가 규칙:

- `complete()`는 MCP 원본 상태가 `OK`일 때만 허용한다.
- `mark_interrupted()`는 `REVIEW_INTERRUPTED`, `retryable=true`,
  `next_action=RETRY_REVIEW` 오류를 만든다.
- 반복 `cancel()`은 동일한 `CANCELLED` 상태를 유지하는 멱등 no-op이다.
- `EXPIRED` 이후에는 모든 전이를 거부한다.
- 상태 전이는 result, error, MCP 상태, 완료 시각과 progress를 함께
  갱신하여 중간의 모순된 조합을 노출하지 않는다.
- 도메인 메서드는 테스트 가능한 명시적 `at` 시각을 받는다.

MCP의 `status`와 애플리케이션의 `ReviewState`는 계속 별도 필드와 Enum으로
유지한다. MCP 호출 자체의 timeout·transport·DTO 오류는 MCP 상태를
조작하지 않고 애플리케이션 오류로 저장한다.

### 2. 실패 재시도는 새 Review를 생성한다

재시도 가능한 `FAILED` Review는 원본 상태를 복원하지 않는다.

```text
FAILED Review
→ retry 요청
→ retry_of_review_id가 원본 ID인 새 QUEUED Review
→ 새 Review만 REVIEWING
```

동일 세션에는 `QUEUED` 또는 `REVIEWING` Review가 하나만 존재할 수 있다.
Application Service의 선행 검사와 SQLite partial unique index를 함께
사용한다.

동일 멱등 키 요청은 프로세스 내부 guard로 직렬화한다. DB unique 경쟁이
발생하면 같은 내부 operation key의 승자 Review와 저장된 응답을 다시
조회하여 동일 응답 replay로 수렴시킨다. 서로 다른 키의 중복 실행은
`REVIEW_ALREADY_RUNNING`으로 거부한다.

### 3. progress를 불변 값 객체와 고정 단계 순서로 관리한다

progress는 외부에서 수정할 수 없는 `ProgressSnapshot`으로 관리하고 API
경계에서 기존 JSON 형태로 변환한다.

단계 순서는 다음으로 고정한다.

```text
PREPARE
→ BATCH_SEARCH
→ RERANK
→ CLAUSE_REVIEW
→ MISSING_DETECTION
→ RESULT_ASSEMBLY
```

기록 규칙:

- `REVIEWING`에서만 progress를 기록한다.
- 저장되는 이벤트의 `sequence`는 직전 값보다 정확히 1 증가한다.
- `percent`는 감소하지 않으며 실행 중에는 최대 99로 제한한다.
- 이전 stage의 늦은 이벤트는 sequence를 포함해 전체를 무시한다.
- 같은 stage에서 `current`가 감소하면 이전 값을 유지한다.
- stage가 앞으로 이동할 때만 `current/total` 재설정을 허용한다.
- 알 수 없는 stage는 현재 stage·수치·percent를 유지하고 안전하게 길이를
  제한한 원본 message와 sequence만 갱신한다.
- NaN, infinity, 음수 progress는 정규화한다.
- `COMPLETED`만 `RESULT_ASSEMBLY`, 100%로 전환한다.
- `FAILED`는 마지막 정상 progress를 보존하며 성공 완료 문구를 만들지
  않는다.

취소 시에는 result, error와 progress message를 폐기한다. 이미 전달된 SSE
sequence와 화면 진행률이 역행하지 않도록 stage, current, total, percent의
비민감 terminal snapshot은 유지하고 sequence를 1 증가시킨다. 이 결정은
`0724-mvp-api-completion.md`의 “취소 시 progress 제거”를 구체화한다.
`EXPIRED` 전환에서는 progress 전체를 제거한다.

### 4. MCP progress message를 구조화한다

MCP는 `ctx.report_progress()`의 message에 다음 JSON 문자열을 전달한다.

```json
{"stage":"CLAUSE_REVIEW","message":"조항별 이탈 분류 중... (7/17)"}
```

API는 stage와 사용자 표시 문구를 분리하여 저장한다. 기존 MCP가 보내는
plain text와 미래의 알 수 없는 stage도 안전한 fallback으로 처리한다.
공개 검토 DTO와 `clause_results`·`missing_standard_clauses` 분리 계약은
변경하지 않는다.

### 5. version 기반 낙관적 잠금으로 stale 저장을 차단한다

`reviews.version`을 추가하고 Repository 저장을 다음 compare-and-set으로
수행한다.

```text
UPDATE reviews
SET ..., version = expected_version + 1
WHERE id = review_id AND version = expected_version
```

영향 행이 없으면 `ConcurrentReviewUpdateError`로 처리한다.

- terminal 상태를 덮을 수 있는 stale progress와 stale 완료는 버린다.
- progress 저장이 TTL 갱신과 충돌하면 최신 `REVIEWING` Review를 한 번
  다시 읽고 같은 이벤트를 재적용한다.
- 취소는 실행 task를 먼저 회수하고 최신 Review를 다시 읽어 제한된 횟수로
  CAS를 재시도한다.
- sliding TTL 갱신도 CAS 충돌 시 최신 Review를 다시 읽는다.

기존 SQLite에 `version` 컬럼이 없으면 시작 시 추가한다. legacy DB에 세션당
active Review가 여러 개 있으면 unique index 생성을 미루고, lifespan의
정상 `mark_interrupted()` 복구와 TTL 재개를 수행한 뒤 index를 보장한다.

### 6. MCP 호출과 파일 I/O 중에는 DB transaction을 유지하지 않는다

runner의 실행 순서는 다음을 유지한다.

```text
짧은 DB transaction: QUEUED → REVIEWING
→ transaction 종료
→ FileStorage를 통한 파일 읽기와 MCP 호출
→ 짧은 DB transaction: COMPLETED 또는 FAILED
```

- stdio MCP는 `FileStorage.local_path()`가 제공하는 통제된 실제 경로를
  사용한다.
- streamable HTTP MCP는 `FileStorage.open()`으로 읽은 내용을 base64와
  원본 파일명으로 전달한다.
- 저장소 경로를 직접 조합하거나 `Path`로 삭제하지 않는다.

### 7. 종료·복구·파일 삭제도 같은 전이 규칙을 사용한다

- lifespan 종료 시 모든 review task를 취소하고
  `gather(return_exceptions=True)`로 회수한 뒤 MCP runtime을 닫는다.
- task가 `CancelledError`를 받으면 최종 결과를 저장하지 않는다.
- 다음 시작에서 남은 `QUEUED/REVIEWING`은 `mark_interrupted()`를 거쳐
  retryable `FAILED`가 되고 Review와 부모 세션 TTL을 다시 시작한다.
- cleanup은 이미 `EXPIRED`인 Review를 건너뛴다.
- 취소, 만료, 재시도 불가능 실패에서는 먼저 DB 상태와
  `storage_key=None`을 commit하고 그 다음 파일을 멱등 삭제한다.
- DB commit 이후 파일 삭제에 실패하면 DB가 참조하지 않는 orphan으로
  남으며 다음 cleanup 주기에서 다시 삭제할 수 있다.

### 8. 완료된 Review도 취소할 수 있다

`DELETE /api/v1/reviews/{review_id}`는 `COMPLETED`와 `FAILED`에도 허용한다.
완료 결과와 원본 파일을 폐기하고 `CANCELLED`로 바꾼다. 반복 DELETE는
성공하며 두 번째 호출은 실제 삭제가 없음을 응답한다.

## 결과

장점:

- 허용되지 않은 상태 전이를 도메인 계층에서 즉시 차단한다.
- 취소·완료·progress 경쟁에서도 terminal 상태가 되돌아가지 않는다.
- retry 이력과 원본 실패 상태를 보존한다.
- 실제 MCP stage가 API와 SSE까지 일관되게 전달된다.
- 재시작, 취소, 만료, cleanup이 같은 전이와 파일 보존 정책을 사용한다.
- legacy SQLite를 유지하면서 version과 active unique 제약을 도입한다.

비용과 제약:

- Review 저장마다 version CAS가 필요하며 충돌 처리 경로가 추가된다.
- in-process guard는 단일 프로세스 최적화이고, 다중 프로세스의 최종
  일관성은 SQLite unique 제약과 승자 재조회에 의존한다.
- schema 보완 로직은 개발 단계의 SQLite 호환을 위한 최소 migration이다.
  더 복잡한 변경에는 Alembic 도입이 필요하다.
- progress는 최신 스냅샷만 저장하므로 SSE 전체 event replay log를
  제공하지 않는다.

## 검증

다음 항목을 자동화 테스트로 검증한다.

- 전체 상태 전이표와 직접 상태/progress 대입 차단
- progress sequence, stage, current, total, percent 불변식
- stale progress·완료와 취소의 CAS 경쟁
- 세션당 active Review unique 제약과 멱등 replay
- 성공, MCP 오류, timeout, task 취소와 재시작 복구
- MCP 호출 중 DB transaction 미유지
- stdio `local_path`와 HTTP base64 파일 전달
- retryable/non-retryable 파일 보존·삭제 순서
- lifespan task 회수와 MCP runtime 종료 순서
- cleanup의 기존 `EXPIRED` 처리와 tombstone 유지
- API 생성·재시도·취소·결과·SSE 계약

검증 결과:

- API: `209 passed, 4 skipped`
- API Ruff: 통과
- MCP unit: `271 passed, 18 deselected`
- API와 MCP `git diff --check`: 통과

## 재검토 조건

다음 중 하나가 발생하면 이 결정을 재검토한다.

- API 서버를 여러 프로세스 또는 여러 인스턴스로 운영한다.
- SQLite 대신 PostgreSQL이나 별도 worker queue를 도입한다.
- MCP가 progress stage를 별도 구조 필드나 replay 가능한 event log로
  제공한다.
- 취소를 표시 상태가 아니라 원격 MCP 작업의 강제 중단으로 보장해야 한다.
- Review 이력과 progress 전체 이벤트를 장기 보존해야 한다.
