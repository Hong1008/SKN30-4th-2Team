# WorkShield 웹 프론트엔드

Vite와 React로 구현한 계약서 검토 화면입니다. 백엔드 API는 기본적으로 같은 Origin의 `/api/v1` 경로를 사용합니다.

## 요구 사항

- Node.js 20 이상
- npm 10 이상
- API 서버 (기본값: `http://localhost:8000`)

## 설치

```powershell
cd web
npm.cmd install
```

PowerShell 실행 정책 때문에 `npm` 명령이 차단되는 환경에서는 `npm.cmd`를 사용합니다.

## 환경 변수

예시 파일을 복사해 로컬 환경 파일을 만듭니다.

```powershell
Copy-Item .env.example .env.local
```

`.env.local`에서 필요에 따라 값을 변경합니다.

```dotenv
# 브라우저가 호출할 API 기본 경로
VITE_API_BASE_URL=/api/v1

# Vite 개발 서버가 /api 요청을 전달할 백엔드 주소
VITE_API_PROXY_TARGET=http://localhost:8000
```

기본값을 그대로 사용할 경우 환경 파일 생성은 선택 사항입니다. `.env.local`은 Git에 포함되지 않습니다.

## 개발 서버 실행

백엔드를 먼저 실행한 뒤 아래 명령으로 프론트엔드를 시작합니다.

```powershell
cd web
npm.cmd run dev
```

터미널에 표시된 주소(일반적으로 `http://localhost:5173`)로 접속합니다. `/api/*` 요청은 `VITE_API_PROXY_TARGET`으로 프록시됩니다.

## 품질 확인 및 프로덕션 빌드

```powershell
cd web
npm.cmd run typecheck
npm.cmd run build
```

빌드 결과는 `web/dist/`에 생성됩니다.

## API 연동 참고

- 세션 Cookie를 사용하므로 모든 API 요청은 `credentials: 'include'`로 전송됩니다.
- 검토 생성·재시도·채팅·제안 요청은 `Idempotency-Key`를 필수로 전송합니다.
- 검토 진행 상태는 SSE를 우선 사용하며, 연결할 수 없으면 polling으로 전환합니다.
- API 명세는 [OpenAPI 문서](../docs/api/openapi.json)를 확인하세요.
