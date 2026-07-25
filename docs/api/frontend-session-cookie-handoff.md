# 프론트엔드 세션 Cookie 연동

대상: `@gyuwon02`

WorkShield의 익명 세션 접근 토큰은 세션 생성 응답의 본문이 아니라
`workshield_session` HttpOnly Cookie로 전달된다.

현재 연결 가능한 핵심 API는 다음과 같다.

- `POST /api/v1/review-sessions`
- `GET /api/v1/review-sessions/{session_id}`
- `PATCH /api/v1/review-sessions/{session_id}/contract-type`
- `POST /api/v1/review-sessions/{session_id}/out-of-scope-confirmation`
- `POST /api/v1/reviews`
- `GET /api/v1/reviews/{review_id}`
- `GET /api/v1/reviews/{review_id}/results`
- `GET /api/v1/reviews/{review_id}/events`
- `POST /api/v1/reviews/{review_id}/retry`
- `GET /api/v1/reviews/{review_id}/grounding?category={category_code}`
- `POST /api/v1/reviews/{review_id}/chat/messages`
- `POST /api/v1/reviews/{review_id}/suggestions`
- `DELETE /api/v1/reviews/{review_id}`
- `GET /api/v1/metadata` (Cookie 불필요, `ETag` 지원)

## 프론트엔드 규칙

- 토큰을 `localStorage`, `sessionStorage`, 전역 상태 또는 URL에 저장하지 않는다.
- `fetch`는 `credentials: "include"`를 사용한다.
- Axios는 `withCredentials: true`를 사용한다.
- 새로고침 복구에는 `session_id`와 `review_id`만 사용한다.
- `404`는 리소스가 없거나 현재 브라우저 세션이 소유하지 않은 경우다.
- `410 SESSION_EXPIRED`는 현재 브라우저가 소유한 세션이 만료된 경우다.
- `POST /api/v1/reviews`, retry, chat, suggestions 요청에는 매 요청 의미별로 고유한 `Idempotency-Key` 헤더를 포함한다.
- 같은 키와 같은 요청은 기존 응답을 반환하며, 같은 키를 다른 요청에 재사용하면 `409 IDEMPOTENCY_KEY_REUSED`를 반환한다.
- SSE가 끊기면 `GET /api/v1/reviews/{review_id}`로 상태를 동기화하고 `Last-Event-ID`와 함께 재연결한다.

## 업로드·범위 판별 응답

지원 파일 형식은 `HWP`, `HWPX`, `PDF`, `DOCX` 네 가지다. 화면의
허용 확장자는 `GET /api/v1/metadata`의 `file_policy.extensions`를
사용한다.

세션 생성과 조회 응답은 MCP 원본 객체 대신 다음 명시적 필드를 제공한다.

- `scope_status`, `scope_message`
- `suggested_contract_type`
- `candidates[].contract_type`, `candidates[].evidence_score`
- `matched_clause_count`, `exclusion_markers`
- `allowed_actions`, `can_start_review`

`evidence_score`는 확률이나 신뢰도가 아닌 결정론적 근거 점수다. MVP
화면에서 사용자에게 신뢰도로 표현하지 않는다.

업로드 오류는 다음과 같이 처리한다.

- `413 FILE_TOO_LARGE`: 최대 크기 초과
- `415 UNSUPPORTED_FILE_TYPE`: 미지원 확장자
- `415 FILE_TYPE_MISMATCH`: 확장자와 실제 형식 불일치
- `422 ENCRYPTED_FILE`: 암호화 파일
- `422 CORRUPTED_FILE`: 손상되거나 읽을 수 없는 파일

`EMPTY_DOCUMENT`는 업로드 파일 손상과 다르다. 파일 구조 검증은
통과했지만 MCP가 검토 가능한 조항을 추출하지 못한 상태이므로
`allowed_actions=["REUPLOAD"]`, `can_start_review=false`로 처리한다.

```ts
await fetch(`${API_BASE_URL}/api/v1/review-sessions/${sessionId}`, {
  credentials: "include",
});
```

로컬 개발에서는 프론트와 API가 동일 사이트의 localhost를 사용한다.
운영에서는 HTTPS가 필요하며 Cookie에 `Secure`가 적용된다.
