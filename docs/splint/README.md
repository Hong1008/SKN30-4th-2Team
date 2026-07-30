# 백엔드 구현 현황

> 구현 기준: `docs/api/api-draft.md`  
> 역할 경계: 백엔드 A가 `READY_TO_REVIEW`까지 처리하고, 백엔드 B가 이후 검토 실행과 결과 처리를 담당한다.

## 작성 규칙

- A와 B는 각자 담당 영역의 상태와 비고를 수정한다.
- 공통 작업은 A·B가 합의한 후 수정한다.
- 구현 기준이 변경되면 `docs/api/api-draft.md`를 먼저 갱신한다.
- 상태는 `예정`, `진행 중`, `검토 요청`, `완료`, `블로커` 중 하나를 사용한다.
- `완료`는 테스트 통과와 main 반영까지 끝난 상태를 의미한다.

## 공통 작업

| 작업 | 상태 | 담당 | 비고 |
| --- | --- | --- | --- |
| 공통 Enum | 완료 | A·B | 구현·자동화 검증·main 반영 완료 |
| 공통 오류 응답 | 완료 | A·B | 공통 envelope와 retryable·next_action 반영 완료 |
| 세션 DTO | 완료 | A·B | 명시적 scope 후보 DTO와 Cookie 접근 계약 반영 완료 |
| 검토 시작 조건 | 완료 | A·B | 유형 선택, 범위 외 확인, 만료·중복 확인 구현 |

## 백엔드 A

담당 범위: 파일 업로드부터 계약 유형 확정 및 `READY_TO_REVIEW`까지

| API | 작업 | 상태 | 비고 |
| --- | --- | --- | --- |
| `POST /api/v1/review-sessions` | 파일 업로드·검증·범위 판별 | 완료 | main 반영 완료. 개인정보 안내 확인값은 발표 시연 범위에서 프론트만 검증 |
| `GET /api/v1/review-sessions/{session_id}` | 세션 상태 복구 | 완료 | Cookie 소유권·만료 복구 자동화 검증 완료 |
| `PATCH /api/v1/review-sessions/{session_id}/contract-type` | 사용자 계약 유형 확정 | 완료 | 활성 MVP 유형과 네 scope 상태 검증 완료 |
| `POST /api/v1/review-sessions/{session_id}/out-of-scope-confirmation` | 범위 외 계약 계속 진행 확인 | 완료 | 유형 선택·확인 순서 검증 완료 |

### A 완료 기준

- 파일 확장자·크기·실제 형식·암호화·손상 여부를 검증한다.
- 서버가 생성한 임시 경로에 파일을 저장한다.
- MCP 범위 판별 결과를 애플리케이션 상태로 변환한다.
- 사용자 선택 유형과 추천 유형을 분리해 저장한다.
- 조건 충족 시 세션을 `READY_TO_REVIEW`로 전환한다.
- 공통 오류 응답과 테스트를 적용한다.

## 백엔드 B

담당 범위: 검토 시작부터 진행 상황·결과 처리까지

| API | 작업 | 상태 | 비고 |
| --- | --- | --- | --- |
| `POST /api/v1/reviews` | 전체 계약 검토 시작 | 완료 | 실제 stdio MCP Review와 main 반영 완료 |
| `GET /api/v1/reviews/{review_id}` | 검토 상태 조회 | 완료 | 소유권·만료·재시작 복구 검증 완료 |
| `GET /api/v1/reviews/{review_id}/events` | SSE 진행 상황 전송 | 완료 | 단조 sequence·terminal 종료·프론트 폴링 복구 검증 완료 |
| `POST /api/v1/reviews/{review_id}/retry` | 재시도 가능한 검토 재실행 | 완료 | fingerprint 멱등성과 파일 보존 검증 완료 |
| `GET /api/v1/reviews/{review_id}/results` | 전체 검토 결과 조회 | 완료 | 조항 결과·MISSING·주의 신호 분리 검증 완료 |

### 후속 API

| API | 상태 | 비고 |
| --- | --- | --- |
| `GET /api/v1/metadata` | 완료 | 캐시·ETag·파일 정책 구현·main 반영 완료 |
| `GET /api/v1/reviews/{review_id}/grounding` | 진행 중 | category와 출처 allowlist 구현, 운영 MCP E2E 대기 |
| `POST /api/v1/reviews/{review_id}/chat/messages` | 진행 중 | API 안전 경계 구현, 운영 LLM 미승인 |
| `POST /api/v1/reviews/{review_id}/suggestions` | 진행 중 | API 안전 경계 구현, 운영 LLM 미승인 |
| `DELETE /api/v1/reviews/{review_id}` | 완료 | 큐 제거·전용 stdio MCP 실행 중단·결과/파일 정리 구현 |
| `POST /api/v1/review-sessions/{session_id}/extend` | 완료 | 세션·최신 review·Cookie 30분 재설정, 일반 조회 자동 연장 제거 |
| 세션 TTL·orphan 정리 | 완료 | 수동 30분 연장·재시작·반복 정리 검증 완료 |

### B 완료 기준

- 검토 시작 전에 세션 조건을 다시 검증한다.
- 중복 검토를 차단하고 멱등성을 보장한다.
- MCP 진행 이벤트를 검토 ID와 연결한다.
- SSE 연결 종료·재연결·폴링 복구를 처리한다.
- 조항 결과와 MISSING 체크리스트를 분리한다.
- 완료·실패·재시도 상태와 테스트를 적용한다.

## 작업 기록

| 날짜 | 담당 | 작업 | 상태 | 블로커·비고 |
| --- | --- | --- | --- | --- |
| 07-24 | A | 업로드·검토 세션 생성 API | 완료 | main 반영 완료. 개인정보 확인값은 발표 시연 범위에서 프론트만 검증 |
| 07-24 | B | 검토 시작 API | 완료 | 공통 세션 DTO 연동·main 반영 완료 |
| 07-25 | A·B | 실제 stdio MCP BE-A·BE-B 사전 점검 | 진행 중 | stdio 통과, 운영 HTTP E2E 대기 |
| 07-26 | A·B | 파일·DTO·멱등성·SSE 보완 및 전체 회귀 | 완료 | 자동화 검증·main 반영 완료 |
| 07-30 | A·B | main 구현 현황·OpenAPI·기획 문서 재대조 | 진행 중 | 핵심 API main 반영 확인. 운영 LLM·MCP E2E는 잔여 |

## 상태 기준

| 상태 | 의미 |
| --- | --- |
| `예정` | 아직 시작하지 않음 |
| `진행 중` | 구현 중 |
| `검토 요청` | PR 또는 코드 리뷰 대기 |
| `완료` | 테스트 통과 및 main 반영 완료 |
| `블로커` | 선행 작업이나 추가 협의 필요 |
