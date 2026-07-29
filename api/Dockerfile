# syntax=docker/dockerfile:1
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /uvx /usr/local/bin/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성은 소스보다 먼저 설치해 image layer cache를 유지한다.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app/ ./app/
COPY main.py ./
RUN uv sync --frozen --no-dev \
    && mkdir -p /app/data/99_uploads

EXPOSE 8000

# readiness는 SQLite와 MCP session을 함께 확인한다. Compose는 MCP가 준비된 뒤
# API를 시작하므로 배포 시 새 웹을 준비되지 않은 API에 연결하지 않는다.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health/ready', timeout=5).read()"

# 운영은 단일 worker로 SQLite write와 MCP session 수명주기를 한 프로세스에 둔다.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
