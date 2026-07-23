# WorkShield

WorkShield는 IT·SW 분야(SW 프리랜서, SI·SM 하도급) 계약서를 표준계약서와 조항별로 자동 비교하고, 관련 법령 조회를 지원하는 AI 계약서 검토 및 LLM 오케스트레이션 플랫폼입니다.

---

## 프로젝트 구조

```text
.
├── api/      # WorkShield 웹 API & LLM 오케스트레이션 계층 (FastAPI)
├── mcp/      # WorkShield MCP 서버 계층 (FastMCP, 계약서 검토·법령 조회 도구)
├── web/      # WorkShield 프론트엔드 웹 애플리케이션
└── docs/     # 프로젝트 문서 (ADR, API 스키마, 요구사항 등)
```

---

## 빠른 시작

저장소를 새로 클론(clone)한 후 MCP 서버 및 API 서버 환경을 구축하고 통합 실행하는 가이드입니다.

### 사전 요구사항

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) (의존성 관리 및 실행)
- [just](https://github.com/casey/just) (MCP 작업 실행 도구)
- Node.js (MCP 의존성 `kordoc` 및 `korean-law-mcp` CLI 실행용)

---

### 설치 및 서버 실행

#### 1. MCP 서버 환경 설정 (`mcp`)

WorkShield MCP 서버는 계약서 파싱, 조항 매칭 및 법령 조회를 담당합니다. 자세한 설정은 [mcp/README.md](mcp/README.md)를 참고합니다.

```bash
cd mcp

# 1) 환경 파일 설정 (기존 파일 존재 시 복붙하세요.)
cp .env.example .env

# 2) 의존성 설치 및 DB 구축 (이미 되있다면 기존 프로젝트에서 sqlite파일과 Chroma인덱스를 복붙하세요.)
just setup
just build-db
```

- **로컬 자동 실행 안내**: 로컬 기본값인 `stdio` transport 환경에서는 API 서버가 `uv`를 활용해 MCP 서버 프로세스를 자식 프로세스로 자동 실행하므로([api/app/llm/mcp/connection.py](api/app/llm/mcp/connection.py)), 별도로 `just run-mcp`를 직접 실행하지 않아도 됩니다.
- (MCP Inspector 독립 테스트(`just run-mcp-ui`) 또는 Streamable HTTP 모드 실행 시에만 수동으로 구동합니다.)

#### 2. API 서버 구동 (`api`)

WorkShield API 서버는 FastAPI를 기반으로 MCP 세션을 연결하고 웹 API를 제공합니다. 자세한 설정은 [api/README.md](api/README.md)를 참고합니다.

```bash
cd ../api

# 1) 환경 파일 설정
cp .env.example .env
# .env를 열고 OPENAI_API_KEY 또는 GEMINI_API_KEY 등 필요한 비밀값을 입력합니다.

# 2) 의존성 동기화
uv sync

# 3) 서버 실행 (로컬 stdio MCP 프로세스 자동 구동)
uv run uvicorn main:app --reload
```

---

## 테스트 및 스키마 검증

### MCP 서버 테스트

```bash
cd mcp
just test unit
```

### API 서버 테스트 및 OpenAPI 스키마 추출

```bash
cd api

# 전체 단위 테스트 실행 (OpenAPI 스키마 최신 여부 검증 포함)
uv run pytest -q

# docs/api/openapi.json 추출 및 저장
uv run python scripts/generate_openapi.py
```

---

## 세부 모듈 참고 문서

각 모듈의 세부 아키텍처, 환경 변수 설정 및 기술 스택은 아래 개별 문서를 참고합니다.

- **MCP 서버 세부 가이드**: [mcp/README.md](mcp/README.md) (FastMCP 도구 목록, 파이프라인 검토 규칙, 품질 기준)
- **API 서버 세부 가이드**: [api/README.md](api/README.md) (FastAPI 구조, LLM Provider 설정, MCP Lifespan 연동)
