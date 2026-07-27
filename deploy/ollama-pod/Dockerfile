FROM golang:1.24-alpine AS auth-proxy-build

WORKDIR /src
COPY auth-proxy.go .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/ollama-auth-proxy auth-proxy.go


FROM ollama/ollama:latest

ENV OLLAMA_HOST=127.0.0.1:11435 \
    OLLAMA_MODELS=/workspace/.ollama/models \
    OLLAMA_NUM_PARALLEL=1

COPY --from=auth-proxy-build /out/ollama-auth-proxy /usr/local/bin/ollama-auth-proxy
COPY start-ollama.sh /usr/local/bin/start-ollama.sh
RUN chmod 755 /usr/local/bin/ollama-auth-proxy /usr/local/bin/start-ollama.sh

EXPOSE 11434

ENTRYPOINT ["/usr/local/bin/start-ollama.sh"]
