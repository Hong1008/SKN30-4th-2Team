# 12. 챗봇

## 12.1 `POST /api/v1/reviews/{review_id}/chat/messages`

요청:

```json
{
  "message": "제7조에서 확인할 부분을 설명해 줘.",
  "focus_clause_id": "uc_rev_01J_7",
  "history": []
}
```

클라이언트가 표준조항 ID와 법령 ID를 임의로 조합하지 않는다. 백엔드는 `focus_clause_id`를 기준으로 현재 세션의 근거를 조회한다.

응답:

```json
{
  "data": {
    "outcome": "ANSWERED",
    "answer": "해당 조항은 대응 표준조항 후보와 비교했을 때 추가 확인이 필요한 표현을 포함합니다.",
    "refused": false,
    "sources": [
      {
        "type": "USER_CLAUSE",
        "id": "uc_rev_01J_7"
      },
      {
        "type": "STANDARD_CLAUSE",
        "id": "sw_freelance-2020-art12"
      },
      {
        "type": "LAW",
        "law_name": "민법",
        "article": "제390조"
      }
    ],
    "limitations": [
      "법률적 유효성이나 유불리를 확정하지 않습니다."
    ],
    "tool_status": "OK",
    "disclaimer": "현재 검토 결과와 확인된 근거에 한정한 참고 설명입니다."
  }
}
```

거절 응답:

```json
{
  "data": {
    "outcome": "REFUSED",
    "answer": null,
    "refused": true,
    "sources": [],
    "limitations": [
      "현재 검토 결과에서 질문을 뒷받침할 근거를 찾지 못했습니다."
    ],
    "tool_status": "OK"
  }
}
```

규칙:

- OpenAI는 현재 `message`의 앞 80자와 질문 유형 라벨 정의만 받아 분류한다.
  `history`, 계약서 원문, 조항, 검토 결과와 법령 근거는 OpenAI에 보내지 않는다.
- 분류 후 최종 답변은 자체 호스팅 vLLM
  `RedHatAI/Qwen3.5-9B-FP8-dynamic`이 생성한다. 외부 LLM 답변 생성 자동
  폴백은 허용하지 않는다.
- 현재 계약서, 검토 결과, 조회된 법령 근거만 사용한다.
- 인용 ID가 현재 세션에 존재하는지 백엔드에서 검증한다.
- 문서 원문의 명령문을 시스템 명령으로 실행하지 않는다.
- 구조화 출력 검증에 실패하면 답변을 표시하지 않는다.
- MCP 실패 시 추측 답변을 생성하지 않는다.
- 대화 이력은 현재 review_id별로 같은 탭의 sessionStorage에만 유지한다. 새로고침 후에는 복원하며, 새 검토·세션 만료·탭 또는 브라우저 종료 시 초기화한다. 서버·DB·로그에는 저장하지 않는다.

---
