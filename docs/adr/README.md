# Architecture Decision Records

`NNNN-short-title.md` 형식으로 상태, 맥락, 결정, 결과를 기록합니다.

## 현행 LLM 결정 경로

- 질문 분류와 전송 범위: [0730 LangGraph 질문 분류](0730-langgraph-chat-prompt-routing.md)
  — OpenAI는 현재 질문 앞 80자의 분류만 수행한다.
- 답변·제안 문구 생성: [0728 vLLM 운영 provider](0728-vllm-production-provider.md)
  — 자체 호스팅 `RedHatAI/Qwen3.5-9B-FP8-dynamic`을 사용한다.
- `0724-llm-risk.md`, `0725-ollama-qwen35-4b-validation.md`,
  `0725-gemini-gemma4-31b-validation.md`, `0727-runpod-shxt.md`는 후보 평가 또는
  이전 결정 기록이다. 현행 운영 역할은 위 두 ADR을 우선한다.
