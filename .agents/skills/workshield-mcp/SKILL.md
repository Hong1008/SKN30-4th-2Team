---
name: workshield-mcp
description: WorkShield MCP로 IT·SW 계약서를 표준계약서와 결정론적으로 비교하고 표준조항·법령 원문을 조회한다. WorkShield MCP 서버 연결, 계약 유형 확인, 전체·선택 조항 검토, 카테고리별 법령 원문 조회, 결과 상태 해석 또는 streamable HTTP 연동이 필요한 경우에 사용한다.
---

# WorkShield MCP

WorkShield는 법률 결론을 내리지 않고 표준 대비 검토 후보와 참고 원문을 반환한다. 항상 결과를 검토 후보로 표시하고, 위법·합법·승소 가능성·계약상 유불리를 단정하지 않는다.

## 연결

기본 연결은 프로젝트의 Python 진입점을 `uv run`으로 실행하는 로컬 stdio 방식이다. MCP 클라이언트 설정에서 아래 프로세스를 자식 프로세스로 실행한다.

```text
command: uv
args: run --project <프로젝트-절대경로> python <프로젝트-절대경로>/src/app.py
env:
  PYTHONPATH: <프로젝트-절대경로>/src
  MCP_TRANSPORT: stdio
```

`file_path`는 이 방식처럼 서버와 파일시스템을 공유할 때만 사용한다. 서버 준비·MCP 설정·HTTP 연결이 필요하면 [references/setup.md](references/setup.md)를 읽는다.

## 기본 검토 흐름

새 클라이언트는 처음 연동할 때 `get_mcp_capabilities`를 호출해 현재 권장 흐름과 호환 도구의 대체 관계를 확인한다. 계약 유형 값은 항상 `list_contract_types`로 조회하며 하드코딩하지 않는다.

- 전체 계약서: 유형이 불명확하면 `assess_contract_scope` → 사용자가 `contract_type` 확인 또는 선택 → `review_contract_candidates` → 필요한 결과에만 `get_category_grounding`을 호출한다. 유형이 이미 확실하면 범위 판별을 건너뛰고 전체 검토를 직접 호출한다.
- 선택 조항: `parse_contract_clauses` → 사용자가 고른 `clauses[].text`에 `classify_clause_candidate`를 호출한다. 표준조항 후보만 탐색할 때는 `match_clause`를 사용한다.
- 표준조항은 전체 검토·후보 검색 응답에 이미 포함된다. `standard://` 리소스는 독립 탐색 또는 저장한 `clause_id` 재조회에만 사용한다.

`parse_contract`, `review_contract`, `classify_clause`, `get_grounding`은 기존 응답 계약을 유지하는 호환 경로다. 신규 연동의 기본 도구로 선택하지 않는다.

도구 선택, 입력 예시, 리소스 URI는 [references/tools-and-workflows.md](references/tools-and-workflows.md)를 읽는다. 상세 도구 스키마 및 명세는 [references/mcp-spec.json](references/mcp-spec.json)을 참고하되, 해당 파일은 용량이 크므로 전체를 한 번에 읽지 말고 검색하여 사용한다.

## 결과 처리 원칙

- `review_contract_candidates`의 `clause_results`는 계약서에 있는 조항의 `NONE` / `EXTRA` / `NO_MATCH` 결과이며, `missing_standard_clauses`는 계약서 전체에서 대응 조항이 보이지 않는 `MISSING` 표준조항 후보다. 둘을 같은 배열이나 같은 의미로 합치지 않는다.
- `NONE`은 표준조항 후보가 있다는 뜻일 뿐 안전·적법성 판단이 아니다. `EXTRA`와 `NO_MATCH`는 각각 추가 확인과 검색 후보 부재를 뜻한다.
- `toxic_patterns`는 표준 대비 상태와 독립적인 주의 문구 유사 신호다. 빈 배열도 안전하다는 뜻이 아니다.
- `get_category_grounding`은 `OK`일 때만 `grounding`을 반환한다. 법령 원문은 참고 자료로만 표시하며, 상태별 원인과 다음 행동을 구분한다.
- 비어 있는 결과 배열을 문제 없음으로 처리하지 말고 응답 `status`와 `message`를 먼저 확인한다.

상태별 사용자 안내와 파일 전송 규칙은 [references/response-and-safety.md](references/response-and-safety.md)를 읽는다.
