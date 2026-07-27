# 0727 프론트엔드 API 연동과 Git 산출물 관리

- 상태: 승인됨
- 날짜: 2026-07-27
- 관련 문서:
  - [OpenAPI 명세](../api/openapi.json)
  - [프론트엔드 실행 안내](../../web/README.md)
  - [프론트엔드 개선 사항](./0724-fe-updates.md)

## 맥락

초기 프론트엔드는 일부 API 요청 형식이 OpenAPI 명세와 다르고, 진행 상태 조회는 polling만 사용했으며 채팅 화면은 Mock 응답을 표시했다. 또한 `web/node_modules`와 `web/dist`의 일부 파일이 이미 Git에 추적되어 있어, `.gitignore` 규칙을 추가해도 빌드·설치 산출물이 변경 사항으로 계속 나타났다.

계약 유형 선택, 범위 외 확인, 검토 시작, 진행 상태 확인, 결과 조회, 채팅 및 제안 기능을 실제 API 명세에 맞춰 연결하고, 팀원이 동일한 방식으로 실행·검증할 수 있는 기준이 필요했다.

## 결정

### 1. API 클라이언트 규약

- API 기본 경로는 `VITE_API_BASE_URL`로 설정하며 기본값은 `/api/v1`이다.
- Cookie 기반 익명 세션을 지원하기 위해 모든 요청에 `credentials: 'include'`를 사용한다.
- 성공 응답은 `{ data, meta }`, 오류 응답은 `{ error, meta }` Envelope로 처리한다.
- `ApiError`는 HTTP 상태와 함께 `code`, `retryable`, `next_action`, `field`, `details`, `meta.request_id`를 보존한다.
- JSON 본문이 있는 요청에만 `Content-Type: application/json`을 추가한다. `FormData` 업로드와 GET 요청에는 강제로 추가하지 않는다.
- 검토 생성·재시도·채팅·제안 요청의 `Idempotency-Key`는 필수 인자로 두고, UI 호출 직전에 `crypto.randomUUID()`로 생성한다.

### 2. 검토 흐름

- 계약 유형 선택 요청 본문은 `{ "selected_contract_type": "..." }`를 사용한다.
- 범위 외 상태에서는 `out-of-scope-confirmation`에 `{ confirmed: true }`를 전송한 뒤에만 검토를 시작한다.
- 409 응답은 `details.review_id`가 제공될 때에만 기존 검토로 이동한다. 식별자가 없으면 임의의 진행 화면으로 이동하지 않고 오류를 표시한다.
- 진행 화면은 SSE(`progress`, `completed`, `failed`)를 우선 구독한다.
- SSE 연결이 실패하면 `GET /reviews/{review_id}` polling으로 전환하며, 화면 종료 시 EventSource와 timer를 정리한다.
- 채팅은 Mock을 사용하지 않고 API의 `answer`, `sources`, `refused`, `limitations`, `disclaimer`를 화면에 반영한다.
- review ID와 clause ID는 URL 경로를 기준으로 사용해 결과·상세·채팅 화면의 새로고침과 공유 URL을 지원한다.

### 3. 개발 환경과 패키지 관리

- `web/.env.example`에 API 기본 경로 및 Vite 프록시 대상 예시를 제공한다.
- `react-router-dom`을 명시적 의존성으로 추가한다.
- 패키지 관리자는 npm으로 통일하고 `pnpm-lock.yaml`은 제거한다.
- 검증 명령은 `npm.cmd run typecheck`, `npm.cmd run build`로 문서화한다. Windows PowerShell에서 실행 정책으로 `npm` 스크립트가 차단될 수 있으므로 `npm.cmd`를 사용한다.
- Figma Make 전용 Vite 플러그인과 설정은 현재 제품 실행에 사용하지 않으므로 제거한다.

### 4. Git 산출물 정책

- `web/node_modules/`, `web/dist/`, `web/.env`, `web/.env.local`, `web/.env.*.local`을 Git에서 무시한다.
- `.env.example`은 팀 공유를 위해 추적한다.
- 이미 추적 중이던 `web/node_modules/`와 `web/dist/`는 `git rm -r --cached`로 index에서 제거한다. 이 작업은 로컬 파일을 삭제하지 않는다.

## 결과

### 장점

- 프론트엔드 요청 구조가 OpenAPI 명세와 일치해 422 및 잘못된 화면 전환 위험을 줄인다.
- 연결 불안정 시에도 polling으로 진행 상태를 복구할 수 있다.
- API 오류의 재시도 가능 여부와 요청 ID를 보존해 사용자 안내 및 장애 추적이 쉬워진다.
- 설치·빌드 산출물과 로컬 환경 값이 커밋에 섞이지 않는다.
- 신규 팀원이 README만으로 동일한 개발 환경을 구성할 수 있다.

### 제약 및 후속 작업

- SSE의 브라우저 `EventSource`는 임의 헤더를 설정할 수 없다. 재연결의 `Last-Event-ID` 처리는 브라우저 기본 재연결 동작에 의존하며, 명시적인 헤더 제어가 필요하면 fetch 기반 SSE 클라이언트를 검토한다.
- API 클라이언트와 화면 흐름에 대한 단위·통합 테스트는 아직 추가하지 않았다. Envelope, 계약 유형 요청, 범위 외 확인, SSE/polling 전환을 우선 테스트 대상으로 삼는다.
- `web/dist`와 `web/node_modules`의 Git 제거는 다음 커밋에서 저장소에 반영된다. 기존 clone에서는 한 번의 pull 뒤 로컬 산출물이 untracked/ignored 상태가 된다.

## 검증

2026-07-27에 다음 명령을 성공적으로 실행했다.

```powershell
cd web
npm.cmd run typecheck
npm.cmd run build
```
