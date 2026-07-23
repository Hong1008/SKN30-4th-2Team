# 0723 API 설정과 의존성 구성

- 상태: 승인됨
- 날짜: 2026-07-23

## 맥락

WorkShield API는 FastAPI로 계약서 업로드·검토 진행 상태·LLM 기반 설명을 오케스트레이션한다.
MCP의 결정론적 검토 결과와 LLM 설명을 분리하고, 로컬 개발에서는 외부 LLM을 선택할 수 있으면서도
운영 환경에서는 계약서가 외부 LLM으로 전송되지 않게 해야 한다.

또한 설정을 각 모듈에서 직접 생성하면 테스트 대체와 환경 일관성이 어려우므로 FastAPI 의존성 주입
방식으로 제공한다.

## 결정

### API 런타임·개발 의존성

`api/pyproject.toml`에 다음 의존성을 둔다.

- API·업로드·진행 이벤트: `fastapi`, `uvicorn[standard]`, `python-multipart`,
  `sse-starlette`, `filetype`
- 설정: `pydantic-settings`
- MCP: `mcp`, `langchain-mcp-adapters`
- LLM 워크플로와 provider: `langgraph`, `langchain-openai`,
  `langchain-google-genai`, `langchain-ollama`
- 개발 검증: `pytest`, `pytest-asyncio`, `httpx`, `ruff`

`langchain-mcp-adapters`는 MCP SDK를 대체하지 않는다. API는 MCP SDK를 직접 사용해 검토 요청,
세션, 진행 이벤트를 제어한다. 어댑터는 LangGraph에서 허용된 MCP 도구만 LangChain Tool로 변환할 때
사용한다. LLM에는 파일 입력 또는 전체 계약서 검토 도구를 포괄적으로 노출하지 않는다.

### LLM provider와 환경 파일

공개 기본 설정은 Git으로 관리하고, 비밀값은 Git에서 제외한다.

| 파일 | Git | 용도 |
| --- | --- | --- |
| `api/.env.local` | 추적 | 로컬 기본값: `APP_ENV=local`, `LLM_PROVIDER=openai` |
| `api/.env.prod` | 추적 | 운영 기본값: `APP_ENV=prod`, `LLM_PROVIDER=ollama` |
| `api/.env` | 비추적 | OpenAI·Gemini API 키와 내부 서비스 URL |
| `api/.env.example` | 추적 | 비밀 설정 파일의 템플릿 |

지원 provider 값은 `openai`, `gemini`, `ollama`다. 프로세스 환경의 `APP_ENV`가 공개 기본 파일을
선택하며, 그 뒤 `api/.env`의 비밀값을 적용한다. 운영 배포는 `APP_ENV=prod`를 명시해야 한다.

운영에서 `LLM_PROVIDER`가 `ollama`가 아니면 Settings 검증에서 API 시작을 차단한다. OpenAI와 Gemini는
로컬 개발에서만 선택한다.

### Settings 의존성 주입

설정은 `api/app/config.py`에 둔다. `main.py`를 포함한 모듈 전역에서 `Settings()`를 생성하지 않는다.

- `get_settings()`는 `lru_cache`로 프로세스당 하나의 `Settings` 인스턴스를 지연 생성한다.
- `SettingsDep = Annotated[Settings, Depends(get_settings)]`를 라우터와 하위 FastAPI 의존성의
  매개변수 타입으로 사용한다.
- 테스트는 `get_settings.cache_clear()` 또는 FastAPI의 `dependency_overrides`로 설정을 대체한다.
- 공통 설정을 위한 별도 `api/app/core/` 계층은 만들지 않고 `api/app/config.py`를 사용한다.

## 결과

- API의 설정 생성 시점과 주입 경로가 일관되고 테스트에서 대체 가능하다.
- 운영 환경의 외부 LLM 사용을 설정 단계에서 방지한다.
- MCP의 진행 상태 제어는 API가 유지하면서도, LangGraph에서 제한된 MCP 도구를 사용할 수 있다.
- 외부 provider 사용에 대한 사용자 동의 흐름은 후속 작업으로 남긴다.

## 추가 기록: LLM provider 구현

`api/app/llm/`에 OpenAI, Gemini, Ollama의 LangChain chat model 생성 계층을 추가했다.
각 구현체는 모델명을 고정하지 않고 `Settings.llm_model`을 사용하며, factory는
`Settings.llm_provider`에 따라 `BaseChatModel` 구현체를 선택한다. 선택한 외부 provider의
API 키와 모델명이 없으면 `LLMConfigurationError`로 생성 단계에서 실패한다.

- `ReasoningMode`는 `off`와 `on`을 제공하고, factory와 `ChatModelDep`의 기본값은 `off`다.
  `ChatModelDep`는 기존 `SettingsDep`를 사용하므로 FastAPI 라우터와 서비스에서 같은 설정
  의존성 경로를 재사용한다.
- OpenAI와 Gemini는 LangChain model profile의 reasoning capability를 확인한다. 추론을
  지원하지 않는 모델에 `on`을 지정하거나, reasoning effort profile상 끌 수 없는 모델에
  `off`를 지정하면 오류를 낸다.
- Gemini/Gemma는 provider의 `thinking_level`로 on/off 요청을 변환한다. capability level이
  명시된 기본-추론 모델은 off를 거부하며, boolean thinking 계약을 제공하는 모델은
  `minimal`/`high`를 off/on으로 사용한다.
- Ollama는 native `reasoning` boolean을 그대로 전달한다. 모델별 지원 여부는 Ollama가
  실제 호출 시 검증하므로 구현체에 특정 모델명 분기를 두지 않는다.

이 구현은 외부 API를 호출하지 않는 TDD 단위 테스트로 검증했다. provider 선택, API 키와
Ollama base URL 전달, 비밀값 비노출, reasoning 변환, 지원하지 않는 reasoning 옵션 오류,
`SettingsDep` 연결을 테스트했다. Gemini 2.5 thinking budget 분기와 특정 모델명 분기 테스트는
추가하지 않았다.

## 검증

- `api/.venv/bin/pytest -q`: Settings 캐시, 운영 provider 제한, `/health`의 설정 의존성 선언 검증
- `api/.venv/bin/ruff check app main.py tests`

## 요구사항 MCP 응답 계약 정규화 기록

이번 세션에서는 [요구사항.json](../requirements/요구사항.json)의 기존 필드는 변경하지 않고, 현행
WorkShield MCP 공개 DTO와 불일치하는 32개 요구사항의 `비고` 끝에 `[신규 MCP 정규화]` 메모만
추가했다.

- 신규 전체 검토 흐름을 `review_contract_candidates`와 필요한 결과에 대한
  `get_category_grounding` 호출로 명시했다. 기존 `review_contract`, `get_grounding`은 호환 경로로
  구분했다.
- 사용자 조항 결과(`clause_results`: `NONE`/`EXTRA`/`NO_MATCH`)와 표준조항 누락 후보
  (`missing_standard_clauses`: `MISSING`)를 분리해 해석하도록 기록했다.
- 대응 표준조항의 신규 경로(`match.status=CANDIDATE_SELECTED`일 때 `match.standard`), 점수,
  카테고리, 버전, 주의 문구, 법령 근거의 조회 경로를 비고에 보완했다.
- MISSING에 `user_clause`가 없는 신규 DTO 구조와, 전체 검토 응답에 `grounding`이 포함되지 않는
  구조를 호환 응답과 구분해 기록했다.

기능 설명, 추가 설명, 런타임 검증 등 다른 요구사항 필드와 그 밖의 파일은 이 작업 범위에서 수정하지
않았다. JSON 파싱과 75개 요구사항의 필드 구조를 검증했다.

## 추가 기록: WorkShield MCP client 구현

`api/app/llm/mcp/`에 WorkShield MCP client 계층을 추가했다. 공개 transport는
`streamable_http`와 `stdio` 두 가지로 제한했다. 로컬 `uv` 실행은 별도 transport가 아니라
stdio의 WorkShield 전용 실행 preset으로 구현한다.

- `streamable_http`는 별도 프로세스·컨테이너의 `WORKSHIELD_MCP_URL`에 연결한다.
- `stdio`는 `uv run --project <mcp-project> python <mcp-project>/src/app.py`를 자식
  프로세스로 실행한다. 프로젝트 경로, `pyproject.toml`, 진입점, `uv` 실행 파일을 시작 전에
  검증하고 shell 문자열 대신 command/args 배열을 사용한다.
- `MCPTransport`, MCP 프로젝트 경로, HTTP·read timeout 설정을 `Settings`에 추가했다.
  로컬 환경은 stdio와 `../mcp`를, 운영 환경은 streamable HTTP를 기본값으로 둔다.

`MultiServerMCPClient.get_tools()`의 기본 stateless 동작은 stdio에서 도구 호출마다 MCP 자식
프로세스를 다시 실행할 수 있으므로 사용하지 않았다. FastAPI lifespan이 하나의 persistent
`ClientSession`을 열고 같은 session에 결합한 LangChain 도구를 앱 종료까지 재사용한다. 시작 시
`get_mcp_capabilities` 도구의 존재와 구조화 응답을 확인하며, 연결·초기화 실패는 API 시작을
중단한다.

MCP runtime과 도구 목록 의존성은 별도 모듈을 만들지 않고 기존 `api/app/llm/dependencies.py`에
`MCPRuntimeDep`, `MCPToolsDep`로 추가했다. lifespan 이전 접근은 503으로 처리한다. runtime의
`supports_file_path`는 stdio에서만 참이며, HTTP에서는 계약 파일을 `file_path`가 아닌 base64
`file_content`와 `file_name`으로 전달해야 한다.

connection 구성, uv stdio 사전 검증, capabilities handshake, session 종료, 애플리케이션 예외
전파, FastAPI lifespan 및 의존성 주입을 외부 MCP 서버 없이 단위 테스트로 검증했다.
