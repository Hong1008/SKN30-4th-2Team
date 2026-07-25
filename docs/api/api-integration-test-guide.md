# 월요일 API 연동 검증 Runbook

## 목표

프론트–BE-A–BE-B–실제 WorkShield MCP 흐름을 같은 테스트 계약서로
검증하고 API 계약, 소유권, 파일 경계와 SSE 종료 조건을 확정한다.

## 역할

| 담당 | 검증 범위 |
|---|---|
| BE-A | metadata, 업로드, 익명 Cookie, 범위 판별, 유형 확정, 시작 조건 |
| BE-B | Review 실행, 상태·결과, 재시도, SSE, FileStorage 사용 |
| 프론트 | Cookie 전송, 상태별 화면, 새로고침 복구, SSE 폴백 |
| 기술리드 | API 계약 변경·블로커·후속 담당 확정 |

## 사전 준비

1. Python 3.13 이상, `uv`, Node.js를 확인한다.
2. `mcp/.env`에 필요한 법령·모델 환경변수를 준비한다.
3. 최초 실행 또는 원천 데이터 변경 시 MCP corpus를 생성한다.

```text
cd mcp
uv sync
just build-db
```

최소한 metadata·범위 분석만 먼저 점검할 때도 SQLite migration은
필수다. `data/migration/contract.sqlite3`가 없거나 0바이트이면 다음을
실행한다.

```text
cd mcp
uv run python src/pipe/0.migrate.py
```

`toxic_patterns` 테이블이 없으면 API metadata는 초기 캐시가 없는 상태에서
`503 MCP_METADATA_UNAVAILABLE`을 반환한다.

4. 민감정보가 없는 HWP, HWPX, PDF, DOCX 테스트 계약서를 준비한다.
5. API 기본 검증을 먼저 통과시킨다.

```text
cd api
uv sync
uv run pytest -q
uv run ruff check app main.py tests
```

## 실제 MCP BE-A 테스트

PowerShell:

```powershell
$env:RUN_WORKSHIELD_INTEGRATION = "1"
$env:WORKSHIELD_INTEGRATION_FILE = "C:\absolute\path\contract.pdf"
$env:WORKSHIELD_MCP_TRANSPORT = "stdio"
uv run pytest -q -m integration tests/integration/test_real_workshield_flow.py -k be_a
```

streamable HTTP를 사용할 때:

```powershell
$env:WORKSHIELD_MCP_TRANSPORT = "streamable_http"
$env:WORKSHIELD_MCP_URL = "http://localhost:8000/mcp"
```

BE-A 통과 조건:

- 필수 MCP 도구 7개가 발견된다.
- metadata의 허용 확장자는 `hwp`, `hwpx`, `pdf`, `docx`다.
- 실제 파일 업로드 후 네 가지 범위 상태 중 하나로 정규화된다.
- HttpOnly Cookie가 발급되고 응답 본문에 토큰이 없다.
- 같은 Cookie로 세션을 복구하고 다른 브라우저는 404를 받는다.
- stdio는 `file_path`, HTTP는 `file_content + file_name` 경로를 사용한다.

## 실제 MCP BE-B Review·SSE 테스트

```powershell
$env:RUN_WORKSHIELD_REVIEW_INTEGRATION = "1"
$env:WORKSHIELD_INTEGRATION_FILE = "C:\absolute\path\contract.pdf"
$env:WORKSHIELD_REVIEW_WAIT_SECONDS = "300"
uv run pytest -q -m integration tests/integration/test_real_workshield_flow.py -k be_b
```

BE-B 통과 조건:

- 공통 세션 Cookie로 Review를 시작한다.
- Review가 `COMPLETED` 또는 계약된 `FAILED` 상태로 종료된다.
- SSE에 동일한 `review_id`가 포함되고 terminal event 후 종료된다.
- 완료 결과의 `clause_results`, `missing_standard_clauses`,
  `toxic_patterns` 배열이 분리된다.
- 다른 브라우저의 상태·SSE 접근은 404다.
- 실제 파일 접근은 FileStorage 인터페이스를 통한다.

## 프론트 수동 검증

1. 브라우저 A에서 파일을 업로드한다.
2. 개발자 도구에서 HttpOnly Cookie와 `credentials: include`를 확인한다.
3. localStorage·sessionStorage·URL에 토큰이 없는지 확인한다.
4. `allowed_actions`, `can_start_review`에 따라 화면이 분기되는지 확인한다.
5. 새로고침 후 `session_id`, `review_id`만으로 복구한다.
6. 시크릿 창에서 같은 ID를 열었을 때 404인지 확인한다.
7. SSE를 끊고 상태 조회 후 재연결되는지 확인한다.

## 장애 검증

| 상황 | 기대 결과 |
|---|---|
| 미지원·암호화·손상·크기 초과 파일 | MCP 호출 전 4xx |
| `EMPTY_DOCUMENT` | Review 시작 차단, 재업로드 안내 |
| `OUT_OF_SCOPE` 미확인 | Review 시작 차단 |
| Cookie 없음·다른 브라우저 | 존재 여부와 무관하게 404 |
| 소유 세션 만료 | 410 |
| MCP timeout | retryable 실패 |
| `CORPUS_UNAVAILABLE`, `PIPELINE_ERROR` | retryable 실패 |
| `INVALID_CONFIG` | 재시도 불가능 실패 |
| SSE 연결 중단 | 상태 조회 후 재연결 |

## 결과 기록

| 항목 | 결과 | 증거 | 담당 | 후속 |
|---|---|---|---|---|
| BE-A 실제 MCP | 대기 | 테스트 로그 | BE-A | |
| BE-B Review/SSE | 대기 | 테스트 로그 | BE-B | |
| 프론트 Cookie | 대기 | Network 캡처 | FE | |
| 브라우저 격리 | 대기 | A/B 응답 | BE-A·BE-B | |
| 장애·재시도 | 대기 | 오류 응답 | BE-B | |
| 운영 로그 비수집 | 대기 | 로그 검색 결과 | 기술리드 | |

실패는 `API 계약`, `프론트 상태 처리`, `소유권/FileStorage`,
`MCP DTO/transport`, `환경·배포` 중 하나로 분류하고 담당자와 재검증
시각을 기록한다.

## 2026-07-25 사전 점검 결과

로컬 stdio와 비민감 PDF fixture로 월요일 실행 절차를 사전 검증했다.

| 항목 | 결과 | 비고 |
|---|---|---|
| MCP 필수 도구 발견 | 통과 | capabilities 및 필수 도구 7개 확인 |
| Metadata | 통과 | SQLite migration 후 계약 유형·파일 정책 조회 |
| BE-A 세션 흐름 | 통과 | 실제 `assess_contract_scope`, Cookie, A/B 격리 |
| BE-B Review | 통과 | 최종 `COMPLETED`, MCP 상태 `OK` |
| SSE·결과 | 통과 | terminal event와 세 결과 배열 확인 |
| stdio 종료 | 통과 | 닫힌 스트림 종료 race를 제한적으로 처리 |

사전 점검에서 다음 두 문제를 발견하고 보완했다.

1. 0바이트 MCP SQLite 때문에 `toxic_patterns` 테이블이 없어 Metadata가
   503을 반환했다. `src/pipe/0.migrate.py`로 160개 표준조항, 90개
   주의 패턴과 관련 데이터를 재생성했다.
2. 실제 LangChain MCP 도구가 반환하는 text content list를 API 공통
   파서가 처리하지 못했다. list/object 양쪽 응답을 처리하는 계약
   테스트를 추가했다.

월요일에는 같은 명령을 팀 환경에서 다시 실행하고 프론트 실제 브라우저
검증 결과를 위 결과 기록 표에 추가한다.
