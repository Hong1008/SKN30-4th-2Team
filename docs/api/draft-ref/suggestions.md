# 13. 협의 문구

## 13.1 `POST /api/v1/reviews/{review_id}/suggestions`

요청:

```json
{
  "user_clause_id": "uc_rev_01J_7",
  "purpose": "책임 범위를 명확히 하기 위한 협의 문구"
}
```

생성 조건:

```text
사용자 조항 존재
AND match.status == CANDIDATE_SELECTED
AND match.standard 존재
```

`NO_MATCH`, `MISSING`, `NO_CANDIDATE`는 기본 생성 대상에서 제외한다.

성공:

```json
{
  "data": {
    "outcome": "GENERATED",
    "text": "손해배상 책임의 범위와 한도는 [금액 확인 필요]로 협의한다.",
    "purpose": "책임 범위를 명확히 하기 위한 협의 문구",
    "key_changes": [
      "책임 한도 확인 항목 추가"
    ],
    "used_source_keys": [
      "SRC_USER",
      "SRC_STANDARD",
      "SRC_GROUNDING"
    ],
    "user_clause_ids": [
      "uc_rev_01J_7"
    ],
    "standard_clause_ids": [
      "sw_freelance-2020-art12"
    ],
    "grounding_source_ids": [
      "law_01"
    ],
    "required_confirmations": [
      {
        "field": "liability_limit",
        "placeholder": "[금액 확인 필요]"
      }
    ],
    "disclaimer": "자동 반영되지 않는 협의용 참고 초안이며 법률 자문이 아닙니다."
  }
}
```

출처 결합 원칙:

- LLM은 실제 `clause_id`나 `source_id`를 생성·복사하지 않고,
  `SRC_USER`, `SRC_STANDARD`, `SRC_GROUNDING`으로 구성된
  `used_source_keys`만 선택한다.
- API는 완료된 검토 스냅샷과 실제 grounding 조회 결과에서 해당 키의
  사용자 조항 ID, 표준조항 ID, 법령 source ID를 결정적으로 결합한다.
- 따라서 반환된 ID는 LLM이 생성한 인용이 아니라 백엔드가 검증된 입력에
  연결한 출처다. `used_source_keys`는 모델이 문구 생성에 사용했다고 선택한
  근거 종류를 나타낸다.

근거 부족:

```json
{
  "data": {
    "outcome": "INSUFFICIENT_GROUNDING",
    "text": null,
    "missing_inputs": [
      "대응 표준조항"
    ]
  }
}
```

MVP에서는 제안 문구를 서버 리소스로 영구 저장하지 않으므로 `suggestion_id`를 필수로 두지 않는다.
