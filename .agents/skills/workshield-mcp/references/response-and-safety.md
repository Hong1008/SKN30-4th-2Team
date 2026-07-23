# 응답 해석과 안전한 사용자 표시

## 전체 응답 상태

| 상태 | 처리 |
| --- | --- |
| `OK` | 결과를 표준 대비 검토 후보로 표시한다. |
| `EMPTY_DOCUMENT` | 조항을 찾지 못했음을 알리고 파일 형식·스캔 품질·`제N조` 구조를 확인하게 한다. |
| `CORPUS_UNAVAILABLE` | 표준 코퍼스가 준비되지 않았음을 알리고 서버 운영자에게 `just build-db` 상태를 확인하게 한다. |
| `INVALID_CONFIG` | 서버 설정 또는 필요한 환경변수를 점검하게 한다. |
| `PIPELINE_ERROR` | 내부 처리 오류로 안내하고 상세 오류를 사용자에게 법률 결론처럼 해석하지 않는다. |

MCP 호출 자체가 실패하면 재시도 가능한 연결 오류인지, 서버가 반환한 정상 응답의 `status` 오류인지 구분한다. 후자의 경우 빈 결과 배열을 성공으로 바꾸지 않는다.

`parse_contract_clauses`와 `assess_contract_scope`가 `EMPTY_DOCUMENT`를 반환하면 이후 검토를 호출하지 않는다. `assess_contract_scope`의 `CONTRACT_TYPE_UNCERTAIN`은 검토 차단이 아닌 경고이므로 사용자가 `contract_type`을 선택하게 한다. `OUT_OF_SCOPE`에서 계속 진행하려면 사용자의 명시적 재확인을 받는다.

## 결과 항목

| 값 | 사용자 표현 |
| --- | --- |
| `NONE` | 표준 대응 후보 있음 |
| `EXTRA` | 별도 확인 필요 |
| `NO_MATCH` | 표준조항 검색 후보 없음 |
| `MISSING` | 계약서 전체 기준 표준조항 누락 가능성 |

`review_contract_candidates`에서는 `NONE` / `EXTRA` / `NO_MATCH`가 `clause_results`에, `MISSING`이 `missing_standard_clauses`에 분리된다. `NO_MATCH`는 특정 사용자 조항에서 표준 후보를 찾지 못한 상태다. `MISSING`은 표준조항 관점에서 계약서 전체에 대응 조항이 보이지 않는 상태다. 두 상태를 같은 의미나 같은 배열로 합치지 않는다.

`toxic_patterns`는 알려진 주의 문구와 유사한 표현의 보조 신호다. 신호가 있더라도 위법·불공정·불리함을 단정하지 않으며, 신호가 없어도 안전·적법을 단정하지 않는다. `review_contract_candidates`에는 `grounding`이 없으므로, 필요한 조항의 `standard.category`와 `contract_type`으로 `get_category_grounding`을 별도 호출한다.

`get_category_grounding`의 `grounding`은 관련 원문 참고자료이며 적용 여부나 해석을 확정하지 않는다. `OK`일 때만 최소 한 건이 있고, `NO_RESULT`, `UNMAPPED_CATEGORY`, `UPSTREAM_ERROR`, `TIMEOUT`에서는 비어 있다. 빈 목록의 원인을 상태별로 표시한다.

## 파일과 개인정보

- stdio에서만 서버가 접근 가능한 로컬 절대 `file_path`를 사용한다.
- HTTP에서는 필요한 파일만 base64로 전달하고 `file_name`에 원래 확장자를 넣는다.
- 계약서와 결과를 사용자 요청 범위 밖으로 전송·공유하지 않는다.
