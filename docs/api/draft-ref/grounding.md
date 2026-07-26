# 11. 법령 근거

## 11.1 `GET /api/v1/reviews/{review_id}/grounding`

Query:

```text
category={category_code}
```

백엔드는 검토 스냅샷의 `contract_type`과 요청의 `category`로 `get_category_grounding`을 호출한다.

응답:

```json
{
  "data": {
    "grounding_status": "OK",
    "category": {
      "code": "LIABILITY",
      "label": "책임·손해배상"
    },
    "contract_type": "SW_FREELANCE",
    "items": [
      {
        "source_id": "law_1",
        "law_name": "민법",
        "article": "제390조",
        "text": "...",
        "source": "국가법령정보센터 또는 출처 좌표",
        "source_url": null
      }
    ],
    "message": null
  }
}
```

정상 빈 결과:

```json
{
  "data": {
    "grounding_status": "NO_RESULT",
    "category": {
      "code": "LIABILITY",
      "label": "책임·손해배상"
    },
    "contract_type": "SW_FREELANCE",
    "items": [],
    "message": "조회된 관련 법령 자료가 없습니다."
  }
}
```

규칙:

- `NO_RESULT`, `UNMAPPED_CATEGORY`는 HTTP 오류가 아닌 정상 응답이다.
- `UPSTREAM_ERROR`, `TIMEOUT`은 오류 응답 또는 동일 구조의 실패 상태로 정규화할 수 있으나 한 방식을 일관되게 사용한다.
- MCP의 `출처`는 URL이라고 보장되지 않으므로 `source`에 보존한다.
- URL 형식으로 검증된 경우에만 `source_url`을 제공한다.
- 법령 조회 실패가 전체 검토 상태를 `FAILED`로 변경하지 않는다.

---

