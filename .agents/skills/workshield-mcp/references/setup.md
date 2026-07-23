# 설치와 연결

## 프로젝트를 내려받아 로컬 stdio로 연결

프로젝트 루트에서 준비한다. Python 3.13 이상, `uv`, Node.js가 필요하며 `just`는 선택 명령을 사용할 때만 필요하다.

```bash
cp .env.example .env
uv sync
```

`.env`에는 환경에 맞게 `LAW_OC`를 설정한다. 로컬 모델 대신 운영 임베딩을 쓸 때는 `APP_ENV=prod`, `RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`도 설정한다.

SQLite와 Chroma는 재생성물이다. 처음 실행하거나 원천 데이터가 바뀐 경우 다음을 실행한다. 이 명령은 Node.js 기반 `kordoc`와 `korean-law-mcp` CLI가 준비돼 있어야 한다.

```bash
just build-db
```

에이전트의 기본 MCP 서버 명령은 다음이다. 실행 디렉터리에 의존하지 않도록 프로젝트 절대경로를 사용한다.

```text
command: uv
args: run --project <프로젝트-절대경로> python <프로젝트-절대경로>/src/app.py
env:
  PYTHONPATH: <프로젝트-절대경로>/src
  MCP_TRANSPORT: stdio
```

터미널에서 직접 확인할 때는 프로젝트 루트에서 실행한다.

```bash
PYTHONPATH=src MCP_TRANSPORT=stdio uv run python src/app.py
```

이 기본 방식에서는 클라이언트와 서버가 같은 파일시스템을 쓰므로, 계약서 도구에 절대 `file_path`를 전달한다.

## 선택: just로 실행

프로젝트의 단축 명령을 사용할 수 있으면 다음도 동일한 stdio 서버를 실행한다.

```bash
just run-mcp
```

초기 개발 환경을 한 번에 구성해야 하면 `just setup`을 쓸 수 있다. 이 명령은 Node.js와 외부 CLI 확인·설치, `uv sync`, 모델 다운로드, migration을 수행하며 API 키 입력을 요청할 수 있다.

## 선택: streamable HTTP

서버와 클라이언트가 다른 파일시스템 또는 다른 호스트에 있으면 HTTP 서버를 별도 프로세스로 실행한다.

```bash
PYTHONPATH=src \
MCP_TRANSPORT=streamable-http \
MCP_HOST=0.0.0.0 \
MCP_PORT=8000 \
uv run python src/app.py
```

연결 URL은 다음이다.

```text
http://localhost:8000/mcp
```

HTTP에서는 서버가 클라이언트의 로컬 파일을 읽을 수 없다. `file_path` 대신 base64 인코딩한 `file_content`와 원래 확장자를 보존한 `file_name`을 함께 전달한다.

Docker를 사용할 경우 `just docker-build` 후 `just docker-run`을 사용한다. 운영 컨테이너는 `APP_ENV=prod`와 RunPod·법령 API 환경변수를 요구한다.
