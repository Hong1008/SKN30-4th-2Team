FROM ollama/ollama:latest

USER root
RUN if command -v apk >/dev/null; then \
        apk add --no-cache python3 py3-pip; \
    else \
        apt-get update && apt-get install -y --no-install-recommends python3 python3-pip \
        && rm -rf /var/lib/apt/lists/*; \
    fi \
    && python3 -m pip install --no-cache-dir --break-system-packages runpod

ARG OLLAMA_MODEL=hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M

ENV OLLAMA_HOST=127.0.0.1:11434 \
    OLLAMA_MODELS=/workspace/.ollama/models \
    OLLAMA_NUM_PARALLEL=1 \
    OLLAMA_MODEL=${OLLAMA_MODEL}

# Serverless worker가 기동될 때 모델 다운로드를 기다리지 않도록 이미지에 포함한다.
RUN ollama serve & ollama_pid="$!"; \
    attempt=0; \
    until ollama list >/dev/null 2>&1; do \
        attempt=$((attempt + 1)); \
        if [ "$attempt" -ge 30 ]; then echo "Ollama 서버 시작 시간을 초과했습니다." >&2; exit 1; fi; \
        sleep 1; \
    done; \
    ollama pull "$OLLAMA_MODEL"; \
    kill -TERM "$ollama_pid"; \
    wait "$ollama_pid" || true

COPY handler.py /app/handler.py
COPY start-serverless.sh /usr/local/bin/start-serverless.sh
RUN chmod 755 /usr/local/bin/start-serverless.sh

ENTRYPOINT ["/usr/local/bin/start-serverless.sh"]
