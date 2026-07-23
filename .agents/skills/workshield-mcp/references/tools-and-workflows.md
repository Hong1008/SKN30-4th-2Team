# 도구와 워크플로우

## 도구 발견

새 클라이언트는 최초 연동 시 `get_mcp_capabilities`를 호출한다. 응답의 `workflows`를 권장 호출 순서로, `legacy_replacements`를 기존 도구의 대체 관계로 사용한다. 이 도구는 계약서나 법령을 조회하지 않는다.

## 전체 계약서 검토

1. `list_contract_types`를 호출해 허용된 `contract_type`을 읽는다.
2. 유형이 불확실하면 `assess_contract_scope`에 계약서를 전달한다.
3. `IN_SCOPE`이면 제안 유형을 기본값으로 제시하고, `CONTRACT_TYPE_UNCERTAIN`이면 사용자가 선택하게 한다. `OUT_OF_SCOPE`는 계속하기 전 재확인을 받는다. `EMPTY_DOCUMENT`면 검토를 호출하지 않는다.
4. 사용자가 선택한 유형과 같은 파일 입력으로 `review_contract_candidates`를 호출한다. 이미 유형이 확실하면 2~3단계를 생략할 수 있다.
5. `clause_results[].match.standard.category` 또는 `missing_standard_clauses[].standard.category`의 법령 원문이 실제로 필요할 때만, 같은 `contract_type`과 함께 `get_category_grounding`을 호출한다.

로컬 stdio의 예시는 다음과 같다.

```json
{
  "contract_type": "<list_contract_types의 값>",
  "file_path": "/absolute/path/to/contract.pdf"
}
```

streamable HTTP의 예시는 다음과 같다.

```json
{
  "contract_type": "<list_contract_types의 값>",
  "file_content": "<파일 바이트의 base64 문자열>",
  "file_name": "contract.pdf"
}
```

`file_path`와 `file_content`/`file_name` 조합은 함께 전달하지 않는다. 지원 형식은 HWP, HWPX, HWPML, PDF, XLS, XLSX, DOCX다.

`review_contract_candidates`는 `clause_results`와 `missing_standard_clauses`를 분리해 반환하고 `grounding` 필드를 포함하지 않는다. 전자는 계약서에 있는 조항의 `NONE` / `EXTRA` / `NO_MATCH` 결과, 후자는 계약서 전체에서 대응되지 않은 `MISSING` 표준조항 후보다. `match.status`가 `CANDIDATE_SELECTED`인 경우에만 `standard`와 정규화 `score`가 있다.

법령 조회는 결과별로 선택한다. `get_category_grounding`의 `OK`는 최소 한 건의 `grounding`을 뜻하고, `NO_RESULT`, `UNMAPPED_CATEGORY`, `UPSTREAM_ERROR`, `TIMEOUT`은 모두 빈 목록이다. 실패·미매핑을 법령이 없거나 문제가 없다는 결론으로 바꾸지 않는다.

## 부분 검토와 조회

| 목적 | 도구 또는 리소스 |
| --- | --- |
| 계약서를 공개 조항으로 분리 | `parse_contract_clauses` |
| 유사 표준조항 후보만 조회 | `match_clause` |
| 한 조항의 표준 대비 상태 판정 | `classify_clause_candidate` |
| 전체 검토와 누락 후보 탐지 | `review_contract_candidates` |
| 계약 유형·카테고리·주의 패턴 조회 | `list_contract_types`, `list_categories`, `list_toxic_patterns`, `list_toxic_pattern_details` |
| 카테고리 기반 법령 원문 참고자료 조회 | `get_category_grounding` |
| 계약 유형별 표준조항 목록 | `standard://{contract_type}` |
| 특정 표준조항 원문 | `standard://{contract_type}/{clause_id}` |

`parse_contract_clauses`의 `clauses[].text`를 선택해 `classify_clause_candidate`에 전달한다. 이 도구는 `MISSING`, `toxic_patterns`, 법령 근거를 만들지 않는다. 전체 문서의 누락 후보 또는 주의 문구 신호가 필요하면 `review_contract_candidates`를 사용한다.

`get_category_grounding`과 법령·판례 프록시 도구는 원문·검색 결과를 제공한다. 이를 근거로 법률 해석을 확정하지 않는다. 자유 법령명 질의처럼 기존 응답이 꼭 필요한 경우에만 호환 도구 `get_grounding`을 사용한다.

## 호환 도구

기존 클라이언트의 응답 파싱을 유지해야 할 때만 아래 도구를 사용한다. 신규 클라이언트는 대응하는 권장 도구를 사용한다.

| 호환 도구 | 권장 도구 |
| --- | --- |
| `parse_contract` | `parse_contract_clauses` |
| `review_contract` | `review_contract_candidates` |
| `classify_clause` | `classify_clause_candidate` |
| `get_grounding` | `get_category_grounding` |

호환 `review_contract`의 조건부 `grounding` 빈 목록을 법령 부재로 해석하지 않는다. 새 흐름에서는 법령 조회를 분리하므로 이 모호성을 피할 수 있다.
