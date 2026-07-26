# 5. 파일 업로드·범위 판별

## 5.1 `POST /api/v1/review-sessions`

Content-Type: `multipart/form-data`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `file` | binary | Y | 계약서 파일 |

자체 호스팅 LLM을 기본 사용하므로 업로드 요청에 외부 LLM 동의 필드를 포함하지 않는다. 외부 LLM 사용 기능을 추가할 경우 공급자·목적·전송 범위·정책 버전을 포함한 별도 동의 계약을 정의한다.

검증 순서:

1. 파일명과 확장자
2. 지원 확장자
3. 최대 파일 크기
4. 확장자와 실제 파일 형식
5. 암호화·손상 여부
6. 서버 생성 임시 경로
7. MCP 입력 XOR 계약
8. `assess_contract_scope`

MCP 입력은 다음 중 하나만 허용한다.

```text
file_path
또는
file_content + file_name
```

## 5.2 정상 범위 판별 응답

성공 `201`:

```json
{
  "data": {
    "session_id": "ses_01J...",
    "review_state": "TYPE_SELECTION_REQUIRED",
    "upload": {
      "file_name": "계약서.pdf",
      "size_bytes": 421398,
      "extension": "pdf"
    },
    "scope_status": "CONTRACT_TYPE_UNCERTAIN",
    "scope_message": "계약 유형을 선택해 주세요.",
    "suggested_contract_type": "SW_FREELANCE",
    "selected_contract_type": null,
    "selection_source": null,
    "candidates": [
      {
        "contract_type": "SW_FREELANCE",
        "evidence_score": 82
      }
    ],
    "matched_clause_count": 8,
    "allowed_actions": ["SELECT_CONTRACT_TYPE"],
    "expires_at": "2026-07-24T10:00:00+09:00"
  }
}
```

`evidence_score`는 MCP의 결정론적 근거 점수를 보존한 값이며 확률·신뢰도·법률 판단이 아니다. MVP 화면에는 숫자를 노출하지 않는다.

## 5.3 빈 문서 응답

확장자·실제 형식 검증은 통과했으나 MCP가 `EMPTY_DOCUMENT`를 반환한 경우 세션을 생성하고 재업로드 상태를 반환한다.

```json
{
  "data": {
    "session_id": "ses_01J...",
    "review_state": "REUPLOAD_REQUIRED",
    "scope_status": "EMPTY_DOCUMENT",
    "scope_message": "검토 가능한 조항을 추출하지 못했습니다.",
    "allowed_actions": ["REUPLOAD"],
    "expires_at": "2026-07-24T10:00:00+09:00"
  }
}
```

이 상태에서는 `POST /reviews`를 허용하지 않는다.

## 5.4 업로드 오류

| 오류 코드 | HTTP |
|---|---:|
| `FILE_EXTENSION_MISSING` | 422 |
| `UNSUPPORTED_FILE_TYPE` | 415 |
| `FILE_TYPE_MISMATCH` | 415 |
| `FILE_TOO_LARGE` | 413 |
| `ENCRYPTED_FILE` | 422 |
| `CORRUPTED_FILE` | 422 |
| `UPLOAD_FAILED` | 500 |

---

## 6. 계약 유형 확정

## 6.1 `PATCH /api/v1/review-sessions/{session_id}/contract-type`

```json
{
  "selected_contract_type": "SW_FREELANCE",
  "selection_source": "SUGGESTED"
}
```

검증:

- 메타데이터의 `enabled_for_mvp=true` 유형만 허용한다.
- 추천 유형과 사용자 선택 유형을 별도 저장한다.
- `CONTRACT_TYPE_UNCERTAIN`에서도 사용자가 선택하면 진행할 수 있다.
- `OUT_OF_SCOPE`는 계약 유형 선택만으로 진행할 수 없으며 계속 진행 확인이 필요하다.

응답:

```json
{
  "data": {
    "session_id": "ses_01J...",
    "scope_status": "IN_SCOPE",
    "suggested_contract_type": "SW_FREELANCE",
    "selected_contract_type": "SW_FREELANCE",
    "selection_source": "SUGGESTED",
    "review_state": "READY_TO_REVIEW",
    "can_start_review": true
  }
}
```

## 6.2 `POST /api/v1/review-sessions/{session_id}/out-of-scope-confirmation`

```json
{
  "confirmed": true
}
```

응답:

```json
{
  "data": {
    "session_id": "ses_01J...",
    "scope_status": "OUT_OF_SCOPE",
    "out_of_scope_confirmed_at": "2026-07-24T09:10:00+09:00",
    "review_state": "READY_TO_REVIEW",
    "can_start_review": true
  }
}
```

`selected_contract_type`이 없으면 확인 후에도 `can_start_review=false`이다.

---

