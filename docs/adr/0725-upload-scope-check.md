# 0725 파일 업로드와 계약 범위 확인

- 상태: 승인됨
- 결정일: 2026-07-25
- 대상 브랜치: `feat/mvp-api`
- 관련 ADR:
  - `0724-anonymous-session-file-storage.md`
  - `0724-mvp-api-completion.md`

## 맥락

BE-A 담당 범위 중 파일 확장자·크기 검증과 MCP
`assess_contract_scope` 호출은 구현되어 있었지만 다음 경계가 남아 있었다.

- PDF, ZIP Office 문서, HWP의 실제 내부 구조 검증
- 암호화 파일과 손상 파일의 MCP 호출 전 차단
- `assess_contract_scope` 선택 필드의 누락·null·잘못된 타입 정규화
- 네 가지 범위 상태와 제품 세션 상태의 통합 검증
- 프론트가 임의의 MCP 원본 dict를 해석하지 않도록 하는 응답 DTO

Review 실행·상태·결과·SSE는 BE-B 담당 범위이므로 이번 변경에서는 해당
동작을 수정하지 않고 전체 회귀 테스트로 영향만 확인했다.

## 결정

### 1. 파일 검증

`review_sessions.file_validation`에서 확장자별 검증을 수행한다.

| 형식 | 검증 내용 |
|---|---|
| PDF | PDF header, xref·trailer·page tree, 암호화 여부 |
| DOCX | ZIP 무결성·크기 제한, 암호화 flag, Content Types와 main XML |
| HWPX | ZIP 무결성·크기 제한, mimetype, version, package, section XML |
| HWP | HWP 3 고정 signature·헤더 또는 OLE `FileHeader`·필수 stream·암호화 property |

제품에서 허용하는 업로드 형식은 `HWP`, `HWPX`, `PDF`, `DOCX`
네 가지로 제한한다. 환경변수로도 이 범위 밖의 형식을 활성화할 수 없다.

검증 순서는 파일명·확장자, 지원 확장자, 크기, 비어 있는 파일, 실제
문서 구조, 암호화·손상 여부 순서다. 모든 검증은 FileStorage 저장과 MCP
호출 전에 수행한다.

오류 상태는 API 초안과 일치시켰다.

| 코드 | HTTP |
|---|---:|
| `UNSUPPORTED_FILE_TYPE` | 415 |
| `FILE_TYPE_MISMATCH` | 415 |
| `FILE_TOO_LARGE` | 413 |
| `ENCRYPTED_FILE` | 422 |
| `CORRUPTED_FILE` | 422 |

PDF와 OLE 문서의 구조·암호화 검증에는 각각 `pypdf`, `olefile`을
사용한다. 기존 magic byte 추측용 `filetype` 의존성은 제거한다.
ZIP 계열은 중복 member, 과도한 member 수·압축 해제 크기, CRC 오류,
과도한 XML, `DOCTYPE`·`ENTITY` 선언을 거부한다. HWP 3은 30바이트
signature와 문서 정보 블록의 암호화·압축·정보 블록 길이를 검증한다.

파일 검증은 FileStorage 저장 전에 끝내며, 저장 후
`assess_contract_scope`가 설정된 시간 안에 완료되지 않으면
`504 MCP_TIMEOUT`으로 응답하고 저장 파일을 삭제한다.

### 2. MCP 범위 판별 응답 정규화

`assess_contract_scope` 결과는 저장 전에 다음 제품 계약으로
정규화한다.

```json
{
  "status": "IN_SCOPE",
  "suggested_contract_type": "SW_FREELANCE",
  "candidates": [
    {
      "contract_type": "SW_FREELANCE",
      "score": 82
    }
  ],
  "matched_clause_count": 3,
  "exclusion_markers": [],
  "message": null
}
```

- `status`는 필수이며 `IN_SCOPE`, `CONTRACT_TYPE_UNCERTAIN`,
  `OUT_OF_SCOPE`, `EMPTY_DOCUMENT`만 허용한다.
- `candidates`, `exclusion_markers`의 누락·null은 빈 배열로 변환한다.
- `matched_clause_count`의 누락·null은 0으로 변환한다.
- 후보의 `contract_type`과 정수 `score`는 필수다.
- 점수의 값과 순서를 보존하며 확률 또는 신뢰도로 변환하지 않는다.
- 잘못된 타입이나 알 수 없는 상태는 `503 MCP_RESPONSE_INVALID`로
  변환한다.
- 저장 이후 정규화가 실패하면 이미 저장한 임시 파일을 삭제한다.

### 3. 세션 응답 DTO

프론트에 MCP 원본 dict를 직접 노출하던 `scope_result`를 제거하고 다음
명시적 필드를 제공한다.

- `scope_status`
- `scope_message`
- `suggested_contract_type`
- `candidates[].contract_type`
- `candidates[].evidence_score`
- `matched_clause_count`
- `exclusion_markers`
- `allowed_actions`
- `can_start_review`

`evidence_score`는 MCP의 결정론적 근거 점수이며 확률·신뢰도·법률 판단이
아니다. 최종 계약 유형을 선택하기 전에는 검토를 시작할 수 없다.
`OUT_OF_SCOPE`는 유형 선택과 계속 진행 확인이 모두 필요하고,
`EMPTY_DOCUMENT`에서는 재업로드만 허용한다.

## 검증

실행 명령:

```text
cd api
uv run pytest -q --basetemp .pytest-full-final
uv run ruff check app main.py tests
uv run python scripts/generate_openapi.py
```

결과:

```text
Pytest: 166 passed, 4 skipped
Ruff: All checks passed
OpenAPI runtime schema 일치
```

주요 추가 검증:

- 정상 PDF, DOCX, HWPX, HWP 3·HWP 5 구조
- HWPML, XLS, XLSX 미지원 형식 차단
- 암호화 PDF
- 손상 PDF·XML·ZIP·HWP와 확장자/실제 형식 불일치
- ZIP bomb 경계와 XML 외부 엔티티 선언 차단
- 미지원 확장자와 10MB 제한 초과
- 잘못된 파일이 MCP 호출 전에 차단되는지 확인
- 잘못된 MCP 응답 시 저장 파일 삭제
- 네 가지 MCP 범위 상태의 제품 상태 변환
- candidates 누락·null·빈 배열·동점과 정수 점수 보존
- OUT_OF_SCOPE 선택·확인 순서와 `can_start_review`
- EMPTY_DOCUMENT 및 비활성 계약 유형 검토 차단
- 실제 저장소의 HWP, HWPX, DOCX, PDF 샘플 14건 구조 검증 통과
- 범위 판별 timeout의 504 응답과 저장 파일 삭제

테스트의 MCP는 동일 tool 인터페이스를 제공하는 fake를 사용했다. 운영
WorkShield MCP 프로세스를 이용한 transport E2E는 배포 환경에서 별도로
수행한다.

## 추가된 테스트 파일과 검증 범위

이번 변경에서는 구현 코드와 함께 다음 테스트 파일을 새로 추가했다. 단위 테스트와
실제 MCP 통합 테스트의 책임을 분리해, 기본 테스트는 외부 프로세스 없이 반복 실행할
수 있고 실제 연동 검증은 필요한 경우에만 명시적으로 실행하도록 구성했다.

### `tests/domains/review_sessions/test_file_validation.py`

업로드된 파일의 확장자만 확인하지 않고 실제 문서 구조를 검사하는 규칙을 검증한다.

- 정상 PDF, DOCX, HWPX, HWP 문서 구조를 허용한다.
- 암호화된 PDF와 HWP 3·HWP 5를 `ENCRYPTED_FILE`로 거부한다.
- 깨진 PDF와 HWP 문서를 `CORRUPTED_FILE`로 거부한다.
- DOCX 확장자를 사용한 일반 ZIP 또는 XLSX 구조를 `FILE_TYPE_MISMATCH`로 거부한다.
- 중복·과다 ZIP member, 압축 해제 크기, XML 구조·크기·엔티티 경계를
  `CORRUPTED_FILE`로 거부한다.
- 제품 범위 밖인 HWPML, XLS, XLSX를 `UNSUPPORTED_FILE_TYPE`으로 거부한다.

이 테스트는 미지원 파일과 손상·암호화 파일이 FileStorage 저장 및 MCP 호출 전에
차단되는지를 보장한다.

### `tests/domains/review_sessions/test_scope_normalization.py`

WorkShield MCP의 `assess_contract_scope` 응답을 제품 세션 상태로 정규화하는 규칙을
검증한다.

- `IN_SCOPE`, `CONTRACT_TYPE_UNCERTAIN`, `OUT_OF_SCOPE`,
  `EMPTY_DOCUMENT` 네 상태를 모두 허용한다.
- 선택 필드의 누락 또는 `null`을 안전한 기본값으로 변환한다.
- 후보의 정수 `score`를 확률이나 신뢰도로 변환하지 않고 그대로 보존한다.
- 알 수 없는 상태, 잘못된 후보 구조, 실수형 점수, 음수 조항 수 등 계약 위반 응답을
  `MCP_RESPONSE_INVALID`로 거부한다.

이 테스트는 MCP 응답 변경이나 누락이 API 내부 상태를 조용히 오염시키지 않도록 한다.

### `tests/domains/review_sessions/test_mcp_tool_payload.py`

LangChain MCP 도구가 반환할 수 있는 여러 응답 포맷을 API 공통 파서가 동일한
payload로 해석하는지 검증한다.

- text content 목록 안의 JSON 응답을 추출한다.
- MCP 객체의 `structuredContent` 응답을 추출한다.
- JSON이 아닌 text 또는 지원하지 않는 content만 있는 응답을
  `MCP_RESPONSE_INVALID`로 거부한다.

실제 stdio 연동에서 발견된 “도구 결과가 dict가 아니라 text content 목록으로
반환되는 경우”를 회귀 테스트로 고정한 것이다.

### `tests/domains/metadata/test_service.py`

WorkShield MCP의 카테고리와 주의 문구 메타데이터를 프론트용 DTO로 정규화하는
경계 조건을 검증한다.

- 카테고리의 `value`, `description`, `anchors`를 코드·표시명·설명·앵커 목록으로
  변환한다.
- 주의 문구의 `pattern`, `title`, `category`, `example_count`를 명시적 DTO로
  변환한다.
- 누락, `null`, 배열이 아닌 응답을 빈 목록으로 안전하게 처리한다.
- 식별자가 없거나 예시 수가 잘못된 항목을 결과에서 제외한다.
- 문자열 목록을 반환하는 이전 MCP 응답과의 호환성을 유지한다.

결과 코드의 기존 문자열 배열은 유지하면서, 프론트가 표시명을 하드코딩하지 않도록
`result_code_details`를 함께 제공하는지도 API 통합 테스트에서 검증한다.

### `tests/integration/test_real_workshield_flow.py`

Mock 도구가 아니라 실제 WorkShield MCP와 API 애플리케이션을 함께 실행하는 선택형
통합 테스트다. 외부 프로세스와 실제 계약서 fixture가 필요하므로 기본 테스트에서는
skip되며, 환경변수를 명시한 경우에만 실행한다.

BE-A 세션 흐름에서는 다음을 검증한다.

- 필수 MCP 도구와 transport 기능 탐지
- 실제 metadata 조회와 파일 정책
- 실제 계약서 업로드 및 `assess_contract_scope` 실행
- HttpOnly Cookie 발급과 응답 본문의 원본 토큰 미노출
- 소유 브라우저의 세션 복구와 다른 브라우저의 404 접근 차단

BE-B 연동 경계에서는 다음을 검증한다.

- 공통 세션으로 Review 생성
- Review가 `COMPLETED` 또는 `FAILED` terminal 상태에 도달하는지 확인
- SSE에 현재 `review_id`와 terminal event가 포함되는지 확인
- 완료 결과의 `clause_results`, `missing_standard_clauses` 분리와
  `clause_results[].toxic_patterns` 정규화 확인
- 다른 브라우저의 Review 상태와 SSE 접근을 404로 차단

실제 연동 테스트 실행 조건은 다음과 같다.

| 환경변수 | 용도 |
|---|---|
| `RUN_WORKSHIELD_INTEGRATION=1` | BE-A 실제 세션 흐름 실행 |
| `RUN_WORKSHIELD_REVIEW_INTEGRATION=1` | Review/SSE 실제 흐름 실행 |
| `WORKSHIELD_INTEGRATION_FILE` | HWP, HWPX, PDF, DOCX 테스트 계약서의 절대 경로 |
| `WORKSHIELD_MCP_TRANSPORT` | `stdio` 또는 `streamable_http` 선택 |
| `WORKSHIELD_REVIEW_WAIT_SECONDS` | Review terminal 상태 대기 제한 |

실행 명령과 사전 준비 사항은
`docs/api/api-integration-test-guide.md`에서 관리한다.

### 테스트 실행 결과

- 파일 검증, scope 및 metadata 정규화 관련 기본 테스트를 포함한 전체 기본 테스트:
  `166 passed, 4 skipped`
- 파일명 정리 후 scope 정규화와 MCP payload 단위 테스트:
  `15 passed`
- 실제 WorkShield MCP stdio 기반 BE-A 세션 흐름: 통과
- 실제 WorkShield MCP stdio 기반 Review/SSE 흐름: 통과
- Ruff 정적 검사: 통과

여기서 기본 테스트의 네 skip은 실제 MCP BE-A·BE-B와 실제 LLM
Chat·Suggestions 연결을 의도적으로 비활성화한 결과이며, 기능 누락이나
실패를 의미하지 않는다. 운영 배포 환경의 URL, 인증, 네트워크 조건까지
포함하는 최종 E2E 검증은 배포 환경에서 별도로 수행한다.

## 결과

BE-A의 파일 업로드, 범위 판별, 계약 유형 확정과 검토 시작 조건은
자동화 테스트 기준으로 완료했다. 월요일 협업 시에는 프론트의 세션 응답
DTO 연동과 BE-B의 공통 소유권·FileStorage 인터페이스 사용 여부를
확인한다.
