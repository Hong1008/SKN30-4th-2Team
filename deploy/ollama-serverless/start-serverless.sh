#!/bin/sh
set -eu

: "${OLLAMA_MODEL:=hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M}"

ollama serve &
ollama_pid="$!"

shutdown() {
  kill -TERM "$ollama_pid" 2>/dev/null || true
  wait "$ollama_pid" 2>/dev/null || true
  exit 0
}
trap shutdown INT TERM

attempt=0
until ollama list >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    echo "Ollama 서버 시작 시간을 초과했습니다." >&2
    exit 1
  fi
  sleep 1
done

echo "Ollama Serverless 모델을 준비합니다: ${OLLAMA_MODEL}"
ollama pull "$OLLAMA_MODEL"

exec python3 -u /app/handler.py
