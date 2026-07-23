# WorkShield API

WorkShield 웹 애플리케이션의 API·LLM 오케스트레이션 계층입니다. FastAPI를 기반으로 계약서 업로드, 검토 진행 상태, MCP(Model Context Protocol) 세션 및 LLM 기반 설명을 관리합니다.

---

## 빠른 시작

### 사전 요구사항

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) (의존성 관리 및 실행)

### 설치

```bash
cd api
uv sync
```

### 환경 파일 설정

```bash
cp .env.example .env
# .env를 열고 OPENAI_API_KEY 또는 GEMINI_API_KEY 등 필요한 비밀값을 입력합니다.
```

| 파일 | Git 추적 | 용도 |
| --- | --- | --- |
| `.env.local` | ✅ | 로컬 개발 기본값 (`APP_ENV=local`, `LLM_PROVIDER=openai`) |
| `.env.prod` | ✅ | 운영 기본값 (`APP_ENV=prod`, `LLM_PROVIDER=ollama`) |
| `.env` | ❌ | API 키 및 내부 서비스 URL (비밀값 보관) |
| `.env.example` | ✅ | `.env` 템플릿 파일 |

- `APP_ENV`를 지정하지 않으면 기본적으로 `.env.local`을 적용합니다.
- 운영 배포 환경에서는 프로세스 환경 변수로 `APP_ENV=prod`를 반드시 지정해야 합니다.

### 서버 실행

```bash
uv run uvicorn main:app --reload
```

---

## 프로젝트 구조

```
api/
├── main.py              # FastAPI 앱 생성, lifespan 및 엔드포인트 진입점
├── pyproject.toml        # 의존성 및 프로젝트 설정
├── app/
│   ├── config.py         # 애플리케이션 전체 공통 Settings 및 SettingsDep (DI)
│   └── llm/              # LLM 및 MCP 오케스트레이션 패키지
│       ├── factory.py        # Settings에 따른 BaseChatModel 생성 factory
│       ├── dependencies.py   # LLM 도메인 전용 FastAPI 의존성 (ChatModelDep, MCPRuntimeDep 등)
│       ├── types.py          # ReasoningMode, LLM 예외 정의
│       ├── provider/         # LLM provider별 구현체 (openai, gemini, ollama)
│       └── mcp/              # WorkShield MCP Client 계층 (connection, client, types)
└── tests/               # 단위 테스트
```

---

## 의존성 주입 (Dependency Injection) 가이드라인

WorkShield API는 모듈 간 결합도를 낮추고 테스트 용이성을 확보하기 위해 FastAPI의 Dependency Injection(DI) 방식을 엄격히 적용합니다.

1. **설정 주입 (`SettingsDep`)**:
   - 모듈이나 라우터 내에서 `Settings()` 인스턴스를 직접 생성하지 않습니다.
   - 애플리케이션 전체 공통 설정은 `app/config.py`에서 제공하는 `SettingsDep`를 매개변수 타입으로 선언하여 주입받습니다.
2. **도메인별 의존성 분리 (`dependencies.py`)**:
   - `SettingsDep`를 제외한 각 패키지/도메인 전용 의존성은 해당 도메인 패키지의 `dependencies.py` 파일에서 각각 독립적으로 관리합니다.
   - (예: LLM provider 모델 인스턴스는 `app/llm/dependencies.py`의 `ChatModelDep`, MCP session/tools는 `app/llm/dependencies.py`의 `MCPRuntimeDep`, `MCPToolsDep` 사용)

```python
# 예시: 라우터/서비스에서의 의존성 주입 사용
from app.config import SettingsDep
from app.llm.dependencies import ChatModelDep


async def analyze_contract(settings: SettingsDep, model: ChatModelDep):
    # settings와 model 인스턴스가 FastAPI DI에 의해 주입됨
    pass
```

---

## LLM Provider

- 지원하는 provider: `openai`, `gemini`, `ollama`
- `factory.py`가 `Settings.llm_provider` 값에 따라 알맞은 `BaseChatModel` 구현체를 생성합니다.
- **운영 환경 제한**: 데이터 보안을 위해 운영 환경(`APP_ENV=prod`)에서는 `LLM_PROVIDER`가 `ollama`가 아닐 경우 API 시작 단계에서 설정을 검증하여 차단합니다.
- **추론 옵션**: `ReasoningMode.off`(기본값) 및 `ReasoningMode.on`을 지원하며 provider별 추론 지원 여부(Reasoning capability)를 검증합니다.

---

## WorkShield MCP 연결

API 서버는 WorkShield MCP 서버와 세션을 유지하며 독자적인 검토 도구 및 실행 환경을 활용합니다.

| 구분 | Transport (`WORKSHIELD_MCP_TRANSPORT`) | 특징 및 계약서 전달 방식 |
| --- | --- | --- |
| **로컬** | `stdio` (기본값) | uv로 `../mcp` 서버를 자식 프로세스로 직접 실행. 파일시스템을 공유하므로 계약서 절대 경로(`file_path`) 사용 |
| **운영/Docker** | `streamable_http` | 외부 MCP URL(`WORKSHIELD_MCP_URL`)에 연결. 로컬 경로 접근이 불가하므로 base64 `file_content` 및 `file_name` 전달 |

- FastAPI **lifespan**이 API 시작 시 하나의 persistent `ClientSession`을 연결하고 종료 시까지 재사용합니다.
- 시작 시 handshake(`get_mcp_capabilities`) 검증 실패 시 API가 준비되지 않은 상태로 시작을 중단합니다.

---

## OpenAPI 스키마 생성 및 문서화

FastAPI 애플리케이션의 라우터 및 Pydantic 모델을 바탕으로 `docs/api/openapi.json` 파일에 스키마를 자동 추출합니다.

```bash
# OpenAPI 3.1 JSON 추출 및 docs/api/openapi.json 저장
uv run python scripts/generate_openapi.py
```

- Pytest 동기화: `uv run pytest` 실행 시 `tests/test_openapi.py`가 `docs/api/openapi.json` 스키마 최신 여부를 자동으로 검증합니다.

---

## 테스트 및 린트

```bash
# 전체 테스트 실행
uv run pytest -q

# ruff 코드 스타일 및 린트 검사
uv run ruff check app main.py tests
```
